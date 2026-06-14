import os
import datetime
import requests
import pickle
import numpy as np
import pandas as pd
from flask import Flask, render_template_string, jsonify
import time
import pandas as pd
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
def crawl_blood_stats():
    url = "https://bloodinfo.net/knrcbs/bi/info/bldStat.do?mi=1047"
    
    # 브라우저 창이 뜨지 않도록 Headless 옵션 설정
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    # 크롬 브라우저 실행
    driver = webdriver.Chrome(options=chrome_options)
    
    try:
        print("💡 대한적십자사 혈액관리본부 페이지에 접속 중입니다...")
        driver.get(url)
        
        # 동적 데이터 테이블이 로드될 때까지 최대 10초 대기
        # 테이블의 클래스명이나 구조에 따라 적절한 요소(예: 테이블 태그)가 나타날 때까지 기다립니다.
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.TAG_NAME, "table"))
        )
        
        # 자바스크립트 렌더링 시간을 주기 위해 2초 추가 대기
        time.sleep(2)
        
        # 렌더링이 완료된 페이지 소스 가져오기
        html = driver.page_source
        soup = BeautifulSoup(html, 'html.parser')
        
        # 페이지 내의 모든 테이블 찾기
        tables = soup.find_all('table')
        if not tables:
            print("❌ 페이지에서 테이블 데이터를 찾을 수 없습니다.")
            return None
        
        # 통계 데이터가 들어있는 메인 테이블 타겟팅 (보통 첫 번째 또는 특정 클래스를 가진 테이블)
        # 사이트 구조에 맞게 class 검색 구문을 튜닝할 수 있습니다.
        target_table = tables[1] 
        
        # 1. 헤더(컬럼명) 추출
        headers = []
        thead = target_table.find('thead')
        if thead:
            headers = [th.get_text(strip=True) for th in thead.find_all('th')]
        
        # 2. 바디(데이터 내용) 추출
        rows_data = []
        tbody = target_table.find('tbody')
        if tbody:
            rows = tbody.find_all('tr')
            for row in rows:
                cols = row.find_all(['td', 'th'])
                cols_text = [col.get_text(strip=True) for col in cols]
                if cols_text:
                    rows_data.append(cols_text)
                    
        # 헤더가 비어있을 경우 데이터 크기에 맞춰 임의 지정
        if not headers and rows_data:
            headers = [f"열_{i}" for i in range(len(rows_data[0]))]
            
        # 3. 데이터프레임으로 변환
        df = pd.DataFrame(rows_data, columns=headers)
        return df

    except Exception as e:
        print(f"❌ 크롤링 중 오류 발생: {e}")
        return None
        
    finally:
        # 반드시 브라우저를 종료하여 메모리 누수 방지
        driver.quit()
        
df = crawl_blood_stats() # 위 크롤링 함수 호출
# 첫 번째 열이 '지역'이고, 특정 열이 '헌혈자수'인 경우 파싱 가공
# 사이트 테이블의 정확한 컬럼 명칭(예: '지역별', '합계' 등)에 맞춰 딕셔너리로 변환합니다.
print(df)
result = {}

for region_col, people_col in [(0, 1), (3, 4)]:
    for region, people in zip(df.iloc[:, region_col],
                              df.iloc[:, people_col]):
        region = region.split(',')[-1].strip()

        result[region] = int(
            people.replace('명', '')
                  .replace(',', '')
                  .strip()
        )

print(result)