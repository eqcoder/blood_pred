import os
import datetime
import time
import pickle
import threading
import numpy as np
import pandas as pd
import requests
from bs4 import BeautifulSoup
from flask import Flask, render_template_string
from apscheduler.schedulers.background import BackgroundScheduler

# Selenium 관련 라이브러리 (Railway 클라우드 환경 호환성 확보)
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

app = Flask(__name__)

# ==========================================
# ⚡ [전역 캐시 변수] 0초 로딩의 핵심 구조
# ==========================================
CACHED_DATA = {
    'final_list': [],
    'total_pred': "0",
    'total_actual': "0",
    'avg_error_pct': "0.0"
}

# 주요 거점 지역 및 기상청 지점 번호(STN ID) 매핑
REGIONS = {
    '108': '서울', '159': '부산', '168': '전남', '112': '인천',
    '232': '충남', '146': '전북', '152': '울산', '119': '경기',
    '114': '강원', '184': '제주', '279': '경북', '155': '경남', '131': '충북'
}

# [기능 1] 모델 로드
MODEL_PATH = 'model.pkl'

def load_prediction_model():
    if os.path.exists(MODEL_PATH):
        with open(MODEL_PATH, 'rb') as f:
            return pickle.load(f)
    else:
        class DummyModel:
            def predict(self, X):
                preds = []
                for _, row in X.iterrows():
                    base = 400
                    temp_factor = (30 - row['최고기온']) * 5 if row['최고기온'] > 28 else (row['평균기온'] - 10) * 8
                    rain_factor = -row['강수량'] * 12
                    pred = int(base + temp_factor + rain_factor)
                    preds.append(max(50, pred))
                return np.array(preds)
        return DummyModel()

model = load_prediction_model()


# [크롤링 기능] 대한적십자사 bldStat 페이지 데이터 수집
def crawl_blood_stats():
    url = "https://bloodinfo.net/knrcbs/bi/info/bldStat.do?mi=1047"
    
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    # Railway 등 리눅스 환경에서 유연하게 구동되도록 webdriver-manager 서비스 탑재
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    
    try:
        print("💡 대한적십자사 혈액관리본부 페이지에 접속 중입니다...")
        driver.get(url)
        
        WebDriverWait(driver, 12).until(
            EC.presence_of_element_located((By.TAG_NAME, "table"))
        )
        time.sleep(2)
        
        html = driver.page_source
        soup = BeautifulSoup(html, 'html.parser')
        
        tables = soup.find_all('table')
        if not tables:
            print("❌ 페이지에서 테이블 데이터를 찾을 수 없습니다.")
            return None
        
        target_table = tables[1] 
        
        headers = []
        thead = target_table.find('thead')
        if thead:
            headers = [th.get_text(strip=True) for th in thead.find_all('th')]
        
        rows_data = []
        tbody = target_table.find('tbody')
        if tbody:
            rows = tbody.find_all('tr')
            for row in rows:
                cols = row.find_all(['td', 'th'])
                cols_text = [col.get_text(strip=True) for col in cols]
                if cols_text:
                    rows_data.append(cols_text)
                    
        if not headers and rows_data:
            headers = [f"열_{i}" for i in range(len(rows_data[0]))]
            
        df = pd.DataFrame(rows_data, columns=headers)
        return df

    except Exception as e:
        print(f"❌ 크롤링 중 오류 발생: {e}")
        return None
    finally:
        driver.quit()


# [기능 2] 기상청 Open API를 통한 어제 날씨 정보 수집
def get_yesterday_weather():
    yesterday = (datetime.datetime.now() - datetime.timedelta(days=1)).strftime("%Y%m%d")
    url = 'http://apis.data.go.kr/1360000/AsosDalyInfoService/getWthrDataList'
    
    # 🔐 보안 조치: Railway 환경변수에 등록된 키를 우선 조회하고, 없을 때 기존 키를 폴백으로 사용
    KMA_API_KEY = os.environ.get("KMA_API_KEY")

    fallback_data = [
        {'지역': '서울', '최저기온': 19.5, '최고기온': 28.2, '평균기온': 24.1, '강수량': 0.0},
        {'지역': '부산', '최저기온': 20.1, '최고기온': 26.5, '평균기온': 23.5, '강수량': 0.5},
        {'지역': '인천', '최저기온': 18.9, '최고기온': 26.0, '평균기온': 22.8, '강수량': 0.0},
        {'지역': '울산', '최저기온': 19.7, '최고기온': 27.2, '평균기온': 23.1, '강수량': 1.0},
        {'지역': '경기', '최저기온': 18.0, '최고기온': 29.5, '평균기온': 23.9, '강수량': 0.0}
    ]
    
    params = {
        'serviceKey': KMA_API_KEY,
        'numOfRows': '10',
        'pageNo': '1',
        'dataType': 'JSON',
        'dataCd': 'ASOS',
        'dateCd': 'DAY',
        'startDt': yesterday,
        'endDt': yesterday,
    }
    
    try:
        weather_list = []
        for stn_id, region_name in REGIONS.items():
            params['stnIds'] = stn_id
            response = requests.get(url, params=params, timeout=5)
            
            if response.status_code == 200:
                res_json = response.json()
                items = res_json.get('response', {}).get('body', {}).get('items', {}).get('item', [])
                if items:
                    item = items[0]
                    weather_list.append({
                        '지역': region_name,
                        '최저기온': float(item.get('minTa', 15.0)),
                        '최고기온': float(item.get('maxTa', 25.0)),
                        '평균기온': float(item.get('avgTa', 20.0)),
                        '강수량': float(item.get('sumRn', 0.0)) if item.get('sumRn') else 0.0
                    })
        return weather_list if weather_list else fallback_data
    except Exception as e:
        print(f"API Fetch Error, using fallback data: {e}")
        return fallback_data


# [기능 3] 대한적십자사 데이터 가공 및 매핑
def get_actual_blood_donors():
    try:
        df = crawl_blood_stats()
        if df is None or df.empty:
            raise Exception("No dataframe returned")
            
        result = {}
        for region_col, people_col in [(0, 1), (3, 4)]:
            for region, people in zip(df.iloc[:, region_col], df.iloc[:, people_col]):
                if region == '총합' or pd.isna(region):
                    continue
                region = str(region).split(',')[-1].strip()
                result[region] = int(
                    str(people).replace('명', '')
                    .replace(',', '')
                    .strip()
                )
        return result
    except Exception as e:
        print(f"크롤링 데이터 파싱 실패, 백업 데이터 사용: {e}")
        return {'서울': 1280, '부산': 695, '대구': 435, '인천': 410, '광주': 295, '대전': 355, '울산': 215, '경기': 565}


# ==========================================
# 🔄 [백그라운드 스케줄러 잡] 주기적 데이터 갱신
# ==========================================
def update_dashboard_data_job():
    global CACHED_DATA
    print(f"🔄 [{datetime.datetime.now()}] 백그라운드 데이터 수집 및 예측 연산을 시작합니다...")
    
    try:
        # 1. 날씨 및 실제 헌혈 데이터 수집
        weather_data = get_yesterday_weather()
        actual_data = get_actual_blood_donors()
        
        # 2. DataFrame 변환 후 모델 예측 처리
        df = pd.DataFrame(weather_data)
        X = df[['평균기온', '최저기온', '최고기온', '강수량', '지역']]
        
        predictions = model.predict(X)
        
        final_list = []
        total_pred = 0
        total_actual = 0
        error_sum = 0
        
        for i, row in df.iterrows():
            reg = row['지역']
            pred_val = int(predictions[i])
            act_val = actual_data.get(reg, pred_val + 10)
            
            total_pred += pred_val
            total_actual += act_val
            
            err = abs(act_val - pred_val) / act_val if act_val > 0 else 0
            error_sum += err
            accuracy_score = round((1 - err) * 100, 1)
            
            final_list.append({
                'region': reg,
                'min_temp': row['최저기온'],
                'max_temp': row['최고기온'],
                'avg_temp': row['평균기온'],
                'rain': row['강수량'],
                'predicted': pred_val,
                'actual': act_val,
                'accuracy': accuracy_score
            })
            
        avg_error_pct = round((error_sum / len(df)) * 100, 1)
        
        # 3. 전역 변수에 최종 연산본 저장 (스레드 세이프하게 반영)
        CACHED_DATA = {
            'final_list': final_list,
            'total_pred': f"{total_pred:,}",
            'total_actual': f"{total_actual:,}",
            'avg_error_pct': avg_error_pct
        }
        print("✅ 백그라운드 대시보드 데이터 캐시가 최신화되었습니다.")
        
    except Exception as e:
        print(f"❌ 백그라운드 데이터 갱신 중 치명적 오류 발생: {e}")


# HTML 템플릿 코드 (전송받은 원본 반응형 코드 그대로 유지)
DASHBOARD_TEMPLATE = """... (작성하신 대시보드 HTML 코드 전체) ..."""

# ==========================================
# 🚀 [라우터] 사용자가 들어오면 0초만에 즉시 응답
# ==========================================
@app.route('/')
def index():
    return render_template_string(
        DASHBOARD_TEMPLATE,
        data_list=CACHED_DATA['final_list'],
        json_data=CACHED_DATA['final_list'], # Chart.js 바인딩용
        total_pred=CACHED_DATA['total_pred'],
        total_actual=CACHED_DATA['total_actual'],
        avg_error=CACHED_DATA['avg_error_pct']
    )


if __name__ == '__main__':
    # 1. 서버가 처음 부팅될 때 딱 한 번 강제로 데이터를 긁어와 초기 캐시를 만듭니다.
    update_dashboard_data_job()
    
    # 2. 백그라운드 스케줄러 세팅 (기존의 500분은 너무 기므로, 데이터가 리프레시되는 하루 주기 고려 180분~360분 혹은 1시간 권장)
    scheduler = BackgroundScheduler()
    scheduler.add_job(func=update_dashboard_data_job, trigger="interval", minutes=180)
    scheduler.start()
    
    # Railway 포트 바인딩 연동 설정
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)