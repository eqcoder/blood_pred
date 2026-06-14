import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import sys

# ==========================================
# 🎨 세련된 그래픽 및 스타일 테마 기본 설정
# ==========================================
plt.style.use('seaborn-v0_8-darkgrid')  # 깔끔한 대시보드형 스타일 배경 적용
plt.rc('font', family='Malgun Gothic', size=11) # 폰트 가독성 최적화
plt.rcParams['axes.unicode_minus'] = False
plt.rcParams['figure.facecolor'] = '#f8f9fa'   # 깔끔한 미색 배경 설정

try:
    # 💾 1. 데이터 기본 로드
    print("📂 엑셀 데이터 파일 로드 중...", flush=True)
    
    df_mask_raw = pd.read_excel('마스크2.xlsx')
    df_mask_raw['날짜'] = pd.to_datetime(df_mask_raw['날짜'])
    df_mask_raw = df_mask_raw.set_index('날짜').sort_index()
    
    df_blood_raw = pd.read_excel('월별.xlsx')
    df_blood_raw['월'] = pd.to_datetime(df_blood_raw['월'])
    df_blood_monthly = df_blood_raw.set_index('월').to_period('M')

    # 🔍 2. 일 단위 시차(Lag) 순회 탐색 (0일 ~ 120일)
    lag_range = range(0, 50)
    results = []

    for lag in lag_range:
        df_mask_shifted = df_mask_raw.shift(periods=lag)
        df_mask_monthly = df_mask_shifted.resample('M').mean().to_period('M')
        
        df_merged = pd.concat([df_mask_monthly['마스크'], df_blood_monthly['총합']], axis=1, join='inner')
        df_merged.columns = ['mask_trend', 'blood_donors']
        
        # 🌟 2023년 이후 데이터 필터링
        df_filtered = df_merged.loc['2016-01':]
        
        corr_value = df_filtered.corr().loc['mask_trend', 'blood_donors']
        results.append({
            'lag_days': lag,
            'correlation': corr_value,
            'abs_correlation': abs(corr_value)
        })

    df_results = pd.DataFrame(results)

    # 🏆 3. 최적의 시차(Best Lag) 도출
    best_match = df_results.loc[df_results['abs_correlation'].idxmax()]
    best_lag = int(best_match['lag_days'])
    best_corr = best_match['correlation']

    print("\n" + "="*50)
    print(f"🎯 [최적 시차 분석 결과]")
    print(f"➡️ 마스크 트렌드가 헌혈자 수보다 【 {best_lag}일 】 선행할 때 매칭률이 가장 높습니다.")
    print(f"➡️ 최적 시차 상관계수 (r): {best_corr:.4f}")
    print("="*50 + "\n")

    # ==========================================
    # 📊 4. 시차별 상관계수 변화 추이 시각화 (디자인 개선)
    # ==========================================
    fig, ax = plt.subplots(figsize=(11, 4.5))
    
    # 그라데이션 느낌의 선 두께 및 부드러운 다크블루 컬러 매칭
    ax.plot(df_results['lag_days'], df_results['correlation'], color='#2c3e50', linewidth=2.5, label='상관계수 (r)')
    
    # 영점 기준선 및 최적 타겟 시점 하이라이트 인터페이스화
    ax.axhline(0, color='#7f8c8d', linestyle='-', linewidth=0.8, alpha=0.5)
    ax.axvline(best_lag, color='#e74c3c', linestyle=':', linewidth=2, 
               label=f'최적 시차 ({best_lag}일, r=0.6)')
    
    # 최적 포인트 마커 추가 구동
    ax.scatter(best_lag, best_corr, color='#e74c3c', s=80, zorder=5, edgecolors='black')

    # 타이틀 및 레이블 디자인 스케일업
    ax.set_title('시차별 마스크-헌혈자 상관계수', fontsize=14, fontweight='bold', pad=15)
    ax.set_xlabel('시차 (단위 : 일)', fontsize=11, labelpad=10)
    ax.set_ylabel('상관계수', fontsize=11, labelpad=10)
    
    # 그리드선 투명도 조절로 정돈된 레이아웃 처리
    ax.grid(True, linestyle='--', alpha=0.5, color='#cbd5e1')
    ax.legend(frameon=True, facecolor='white', edgecolor='none', fontsize=10)
    
    sns.despine(left=True, bottom=True) # 외곽 테두리선 제거로 플랫 디자인 유도
    plt.tight_layout()
    plt.show()

    # ==========================================
    # 📈 5. 최적 시차 적용된 두 지표의 최종 추이 시각화 (디자인 개선)
    # ==========================================
    df_best_mask_monthly = df_mask_raw.shift(best_lag).resample('M').mean().to_period('M')
    df_final = pd.concat([df_best_mask_monthly['마스크'], df_blood_monthly['총합']], axis=1, join='inner').loc['2023-01':]
    df_final.columns = ['최적시차_마스크', '헌혈자수']
    df_final.index = df_final.index.to_timestamp()

    fig, ax1 = plt.subplots(figsize=(13, 5.5))

    # Y1 축: 마스크 트렌드 (소프트 로즈 오렌지 계열)
    color_mask = "#201986"
    ax1.set_xlabel('년월', fontsize=11, labelpad=10)
    ax1.set_ylabel(f'마스크 검색 트렌드 지수', color=color_mask, fontsize=11, fontweight='bold')
    line1 = ax1.plot(df_final.index, df_final['최적시차_마스크'], color=color_mask, marker='o', markersize=5, linewidth=2.5, label='마스크 트렌드 지수')
    ax1.tick_params(axis='y', labelcolor=color_mask)
    ax1.grid(True, linestyle='--', alpha=0.4, color='#cbd5e1')

    # Y2 축: 헌혈자 수 (세련된 딥 시안/네온 블루 블렌딩 계열)
    ax2 = ax1.twinx()
    color_blood = "#92170adc"
    ax2.set_ylabel('월별 헌혈 참여자 수 (명)', color=color_blood, fontsize=11, fontweight='bold')
    line2 = ax2.plot(df_final.index, df_final['헌혈자수'], color=color_blood, marker='v', markersize=5, linewidth=2.2, label='실제 헌혈자 수')
    ax2.tick_params(axis='y', labelcolor=color_blood)

    # 이중 축 범례(Legend) 통합 레이블 박스화
    lines = line1 + line2
    labels = [l.get_label() for l in lines]
    ax1.legend(lines, labels, loc='upper right', frameon=True, facecolor='white', edgecolor='none')

    plt.title(f'21일 시차 기준 마스크-헌혈자 추이', fontsize=15, fontweight='bold', pad=20)
    sns.despine(ax=ax1, left=False, bottom=True, right=True)
    sns.despine(ax=ax2, left=True, bottom=True, right=False)
    
    fig.tight_layout()
    plt.show()

except Exception as e:
    print(f"❌ 분석 중 에러 발생: {e}", file=sys.stderr)