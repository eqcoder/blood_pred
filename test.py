import datetime
import requests
import json

def get_seoul_yesterday_weather(api_key):
    # 1. 어제 날짜 자동 계산 (YYYYMMDD 형식)
    yesterday = (datetime.datetime.now() - datetime.timedelta(days=1)).strftime("%Y%m%d")
    print(f"📅 데이터 조회 기준일 (어제): {yesterday}")

    # 2. 기상청 ASOS 일자료 API 엔드포인트 URL
    url = 'http://apis.data.go.kr/1360000/AsosDalyInfoService/getWthrDataList'
    
    # 3. 요청 파라미터 설정
    params = {
        'serviceKey': 'fda216c190ae3c833a8e25ba488f74fa4131958e2076da72ba0153d8000b7bba',          # 공공데이터포털에서 발급받은 인증키 (인코딩된 키 권장)
        'numOfRows': '10',              # 한 페이지 결과 수
        'pageNo': '1',                  # 페이지 번호
        'dataType': 'JSON',             # 응답 데이터 타입 (JSON)
        'dataCd': 'ASOS',               # 자료 분류 코드
        'dateCd': 'DAY',                # 날짜 분류 코드 (일 단위)
        'startDt': yesterday,           # 조회 시작일
        'endDt': yesterday,             # 조회 종료일
        'stnIds': '108'                 # 지점 번호 (108은 '서울'을 의미합니다)
    }

    try:
        # API 호출
        response = requests.get(url, params=params, timeout=10)
        
        # 응답 상태 확인
        if response.status_code == 200:
            res_json = response.json()
            
            # API 내부 결과 코드 확인
            result_code = res_json.get('response', {}).get('header', {}).get('resultCode')
            if result_code == '00':
                items = res_json.get('response', {}).get('body', {}).get('items', {}).get('item', [])
                
                if items:
                    data = items[0]
                    
                    # 4. 필요한 항목 파싱 (데이터가 비어있는 경우를 대비해 예외 처리 및 기본값 설정)
                    avg_ta = data.get('avgTa')       # 평균기온
                    min_ta = data.get('minTa')       # 최저기온
                    max_ta = data.get('maxTa')       # 최고기온
                    
                    # 강수량은 비가 안 오면 값이 비어있거나('') 공백일 수 있으므로 0.0 처리
                    sum_rn = data.get('sumRn')
                    sum_rn = float(sum_rn) if sum_rn and sum_rn.strip() else 0.0

                    print("\n☀️ [서울 어제 날씨 정보 수집 성공]")
                    print(f"🔹 평균 기온 (avgTa): {avg_ta}°C")
                    print(f"🔹 최저 기온 (minTa): {min_ta}°C")
                    print(f"🔹 최고 기온 (maxTa): {max_ta}°C")
                    print(f"🔹 일 강수량 (sumRn): {sum_rn}mm")
                    
                    # 예측 모델(model.pkl) 입력 포맷에 맞춰 데이터 반환
                    return {
                        'avgTa': float(avg_ta),
                        'minTa': float(min_ta),
                        'maxTa': float(max_ta),
                        'sumRn': float(sum_rn)
                    }
                else:
                    print("❌ 해당 날짜의 데이터가 아직 기상청 시스템에 업데이트되지 않았습니다.")
            else:
                result_msg = res_json.get('response', {}).get('header', {}).get('resultMsg')
                print(f"❌ 기상청 API 에러 ({result_code}): {result_msg}")
        else:
            print(f"❌ HTTP 연결 실패 (상태 코드: {response.status_code})")
            
    except Exception as e:
        print(f"❌ API 호출 중 예외 발생: {e}")
        
    return None

if __name__ == "__main__":
    # ⚠️ 이곳에 공공데이터포털에서 발급받은 본인의 '일반 인증키(Encoding)'를 넣으세요.
    MY_API_KEY = "YOUR_PUBLIC_DATA_PORTAL_API_KEY"
    
    weather_result = get_seoul_yesterday_weather(MY_API_KEY)