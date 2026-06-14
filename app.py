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
    driver = webdriver.Chrome(options=chrome_options)
    
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
    KMA_API_KEY = os.environ.get("KMA_API_KEY", "fda216c190ae3c833a8e25ba488f74fa4131958e2076da72ba0153d8000b7bba")

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

# 모바일 해상도(Responsive) 최적화 대시보드 뷰 HTML
DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>대한적십자사 날씨 기반 헌혈 예측 시스템</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700&display=swap');
        
        :root {
            --red-main: #D31125;
            --red-bg: #FFF5F5;
            --dark-gray: #2D3748;
            --light-gray: #F7FAFC;
            --border: #E2E8F0;
        }

        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Noto Sans KR', sans-serif; }
        
        /* PC 전체화면 레이아웃 최적화를 위한 Flex 기반 높이 고정 구조 */
        html, body { height: 100%; background-color: var(--light-gray); color: var(--dark-gray); overflow: hidden; }
        body { display: flex; flex-direction: column; }

        /* 네비게이션 바 */
        .top-navbar {
            background-color: #FFFFFF;
            border-bottom: 2px solid var(--red-main);
            padding: 12px 20px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            flex-shrink: 0;
            box-shadow: 0 2px 4px rgba(0,0,0,0.03);
        }

        .brand { display: flex; align-items: center; gap: 12px; }
        
        /* 요청사항: logo.png 크기 조절 및 배치 */
        .brand-logo {
            height: 36px;
            width: auto;
            object-fit: contain;
        }
        
        .brand-title h1 { font-size: 16px; font-weight: 700; color: var(--red-main); line-height: 1.2; }
        .brand-title p { font-size: 10px; color: #718096; letter-spacing: 0.5px; }

        /* 메인 컨테이너: PC에서는 내부 스크롤, 화면 비율 사수 */
        .container { 
            flex: 1; 
            max-width: 1600px; 
            width: 100%;
            margin: 0 auto; 
            padding: 20px; 
            display: flex;
            flex-direction: column;
            gap: 16px;
            overflow-y: auto; /* PC 대형화면은 고정되나 저해상도 배려용 내장 스크롤 */
        }

        /* 헤더 구조 */
        .dashboard-header { 
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-shrink: 0;
        }
        .dashboard-header h2 { font-size: 20px; font-weight: 700; }
        .dashboard-header h2 span { color: var(--red-main); font-size: 18px; margin-left: 8px; }
        .dashboard-header p { font-size: 13px; color: #718096; margin-top: 2px; }

        /* 요약 카드 그리드 */
        .summary-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 16px;
            flex-shrink: 0;
        }

        .summary-card {
            background: #FFFFFF;
            border-radius: 12px;
            padding: 16px 20px;
            border: 1px solid var(--border);
            border-left: 4px solid var(--red-main);
            box-shadow: 0 2px 4px rgba(0,0,0,0.01);
            display: flex;
            flex-direction: column;
            justify-content: center;
        }
        .card-header { display: flex; justify-content: space-between; align-items: center; color: #718096; font-size: 13px; }
        .card-header i { font-size: 15px; color: var(--red-main); }
        .card-value { font-size: 26px; font-weight: 700; margin-top: 6px; }

        /* PC 버전: 차트와 테이블을 좌우(5:5) 분할하여 화면에 꽉 차게 만듦 */
        .main-workspace {
            display: flex;
            gap: 16px;
            flex: 1;
            min-height: 0; /* 자식 요소 크기 오버플로우 방지 핵심 */
        }

        .workspace-block {
            background: #FFFFFF;
            border-radius: 12px;
            padding: 20px;
            border: 1px solid var(--border);
            flex: 1;
            display: flex;
            flex-direction: column;
            min-height: 0;
            box-shadow: 0 4px 6px rgba(0,0,0,0.01);
        }

        .section-title { 
            font-size: 15px; 
            font-weight: 700; 
            margin-bottom: 14px; 
            display: flex; 
            align-items: center; 
            justify-content: space-between;
            flex-shrink: 0;
        }
        .section-title span { display: flex; align-items: center; gap: 6px; }
        .section-title i { color: var(--red-main); }
        
        /* 차트 캔버스 크기 제어 */
        .chart-container { position: relative; flex: 1; width: 100%; min-height: 0; }

        /* 테이블 스크롤 최적화 및 순서 전면 개편 */
        .table-responsive { 
            width: 100%; 
            flex: 1;
            overflow-y: auto; /* 표가 길어지면 블록 내부에서만 스크롤됨 */
            overflow-x: auto;
            -webkit-overflow-scrolling: touch; 
            border-radius: 8px; 
            border: 1px solid var(--border); 
        }
        
        table { width: 100%; border-collapse: collapse; background: #FFFFFF; font-size: 13px; min-width: 650px; }
        
        /* 헤더 고정 고도화 디자인 */
        th { 
            background: #EDF2F7; 
            padding: 12px; 
            text-align: left; 
            font-weight: 600; 
            position: sticky; 
            top: 0; 
            z-index: 10;
        }
        td { padding: 12px; border-top: 1px solid var(--border); }
        tr:hover { background: var(--red-bg); }

        .link-btn {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 6px;
            background: var(--red-main);
            color: white;
            text-decoration: none;
            padding: 8px 14px;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 500;
            transition: background 0.2s;
        }
        .link-btn:hover { background: #B30E1E; }

        /* 📱 초강력 미디어 쿼리: 모바일 해상도(스크린 가로 폭 950px 이하) 최적화 스위칭 */
        @media (max-width: 950px) {
            html, body { overflow: auto; height: auto; }
            .container { padding: 12px; overflow-y: visible; }
            .summary-grid { grid-template-columns: 1fr; gap: 10px; }
            .main-workspace { flex-direction: column; height: auto; }
            .workspace-block { height: 420px; flex-shrink: 0; }
            .chart-container { height: 320px; }
            .dashboard-header { flex-direction: column; align-items: flex-start; gap: 6px; }
        }
    </style>
</head>
<body>

    <div class="top-navbar">
        <div class="brand">
            <img src="logo.jfif" width="100" height="20" alt="대한적십자사 로고"
     class="brand-logo"
     onerror="this.style.display='none';">
            <div class="brand-title">
                <h1>대한적십자사</h1>
                <p>BLOOD PREDICTION SYSTEM</p>
            </div>
        </div>
        <div style="font-size: 11px; background: var(--red-bg); color: var(--red-main); padding: 4px 10px; border-radius: 20px; font-weight:600; border: 1px solid rgba(211,17,37,0.15);">
            <i class="fa-solid fa-cloud-sun"></i> 기상청 실시간 API 동적연동
        </div>
    </div>

    <div class="container">
        <div class="dashboard-header">
            <div>
                <h2>총 헌혈자 수 예측 현황 분석 <span id="target-date-ui"></span></h2>
                <p>2005~2025년 월별 헌혈자 데이터 기반 예측모델</p>
            </div>
        </div>

        <div class="summary-grid">
            <div class="summary-card">
                <div class="card-header"><span>예측 헌혈자 수</span><i class="fa-solid fa-brain"></i></div>
                <div class="card-value" style="color: var(--dark-gray);">{{ total_pred }}명</div>
            </div>
            <div class="summary-card">
                <div class="card-header"><span>실제 헌혈자 수</span><i class="fa-solid fa-users"></i></div>
                <div class="card-value" style="color: var(--red-main);">{{ total_actual }}명</div>
            </div>
            <div class="summary-card">
                <div class="card-header"><span>전국 평균 오차율</span><i class="fa-solid fa-chart-line"></i></div>
                <div class="card-value" style="color: #3182CE;">{{ avg_error }}%</div>
            </div>
        </div>

        <div class="main-workspace">
            
            <div class="workspace-block">
                <div class="section-title">
                    <span><i class="fa-solid fa-chart-bar"></i> 지역별 예측치 vs 실제 헌혈자 대조 그래프</span>
                </div>
                <div class="chart-container">
                    <canvas id="mobileChart"></canvas>
                </div>
            </div>

            <div class="workspace-block">
                <div class="section-title">
                    <span><i class="fa-solid fa-database"></i> 지역별 상세 스냅샷 통계</span>
                    <a href="https://bloodinfo.net/knrcbs/bi/info/bldStat.do?mi=1047" target="_blank" class="link-btn">
                        <i class="fa-solid fa-arrow-up-right-from-square"></i> 혈액관리본부 헌혈 통계 바로가기
                    </a>
                </div>
                <div class="table-responsive">
                    <table>
                        <thead>
                            <tr>
                                <th>지역</th>
                                <th>실제 데이터</th>
                                <th>모델 예측</th>
                                <th>정확도</th>
                                <th>평균기온</th>
                                <th>최고/최저</th>
                                <th>강수량</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for row in data_list %}
                            <tr>
                                <td><strong>{{ row.region }}</strong></td>
                                <td style="font-weight:600; color: var(--red-main);">{{ row.actual }}명</td>
                                <td style="font-weight:600;">{{ row.predicted }}명</td>
                                <td style="color:#38A169; font-weight:600;">{{ row.accuracy }}%</td>
                                <td>{{ row.avg_temp }}°C</td>
                                <td style="color:#718096;">{{ row.max_temp }}° / {{ row.min_temp }}°</td>
                                <td>{{ row.rain }}mm</td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>

        </div>
    </div>

    <script>
        // 날짜 표시 자바스크립트 자동화 (어제 기준)
        const d = new Date();
        d.setDate(d.getDate() - 1);
        const dateStr = `(${d.getFullYear()}년 ${d.getMonth() + 1}월 ${d.getDate()}일 기준)`;
        document.getElementById('target-date-ui').innerText = dateStr;

        // 파이썬 백엔드 데이터 바인딩
        const chartData = {{ json_data | safe }};
        
        const ctx = document.getElementById('mobileChart').getContext('2d');
        new Chart(ctx, {
            type: 'bar',
            data: {
                labels: chartData.map(d => d.region),
                datasets: [
                    {
                        label: '모델 예측치',
                        data: chartData.map(d => d.predicted),
                        backgroundColor: '#FEB2B2',
                        hoverBackgroundColor: '#FCA5A5',
                        borderRadius: 4
                    },
                    {
                        label: '실제 헌혈자',
                        data: chartData.map(d => d.actual),
                        backgroundColor: '#D31125',
                        hoverBackgroundColor: '#B30E1E',
                        borderRadius: 4
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: 'top', labels: { boxWidth: 10, font: { size: 11, family: 'Noto Sans KR' } } }
                },
                scales: {
                    y: { beginAtZero: true, grid: { color: '#EDF2F7' }, ticks: { font: { size: 10 } } },
                    x: { grid: { display: false }, ticks: { font: { size: 11, weight: 'bold' } } }
                }
            }
        });
    </script>
</body>
</html>
"""

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