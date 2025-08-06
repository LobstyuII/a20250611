import os
import xarray as xr
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
import logging
from concurrent.futures import ProcessPoolExecutor, as_completed
import matplotlib.dates as mdates
from scipy.optimize import curve_fit
from statsmodels.nonparametric.smoothers_lowess import lowess
from sklearn.linear_model import RidgeCV
from sklearn.preprocessing import SplineTransformer, PolynomialFeatures
from sklearn.pipeline import make_pipeline

# 配置科研级字体
plt.rcParams['font.family'] = 'serif'
plt.rcParams['font.serif'] = ['Times New Roman']
plt.rcParams['mathtext.fontset'] = 'stix'
plt.rcParams['axes.edgecolor'] = 'black'
plt.rcParams['axes.linewidth'] = 1.0

# 配置日志
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()

# 配置路径
INPUT_DIR = r"D:\H8_data\NDVI_TimeSeries"
OUTPUT_DIR = r"D:\H8_data\NDVI_Decomposition"

# 植被生长曲线参数
MAX_ITERATIONS = 100
CONVERGENCE_TOL = 1e-5


def prepare_station_data(ndvi_series, status_series, time_index):
    """准备站点数据：重采样为小时频率并处理缺失值"""
    time_index = pd.to_datetime(time_index)
    ts = pd.Series(ndvi_series, index=time_index)
    status_ts = pd.Series(status_series, index=time_index)

    # 创建完整时间索引
    start_time = time_index[0].replace(hour=0, minute=0, second=0)
    end_time = time_index[-1].replace(hour=23, minute=0, second=0)
    full_time_index = pd.date_range(start=start_time, end=end_time, freq='h')

    # 重新索引
    ts_full = ts.reindex(full_time_index)
    status_ts_full = status_ts.reindex(full_time_index, method='ffill')

    # 处理缺失值和夜间数据
    mask = (status_ts_full == -1) | ts_full.isnull()
    ts_full[mask] = np.nan

    # 使用低通滤波填充缺失值 - FIXED VERSION
    logger.info("应用低通滤波处理缺失值")
    not_null = ~ts_full.isnull()
    if not_null.sum() > 0:  # 确保有非空值
        filled = lowess(ts_full[not_null],
                        np.arange(len(ts_full))[not_null],
                        frac=0.05,
                        return_sorted=False)

        # 创建插值器并应用于缺失值
        from scipy.interpolate import interp1d
        interp = interp1d(np.arange(len(ts_full))[not_null],
                          filled,
                          kind='linear',
                          bounds_error=False,
                          fill_value='extrapolate')
        ts_full[ts_full.isnull()] = interp(np.arange(len(ts_full))[ts_full.isnull()])

    return ts_full, status_ts_full


def double_logistic(t, sos, eos, length, max_val, min_val):
    """双逻辑斯蒂函数模拟植被生长季"""
    # 计算生长季开始和结束
    greenup = 1 / (1 + np.exp(-20 * (t - sos) / length))
    senescence = 1 / (1 + np.exp(20 * (t - eos) / length))

    # 生长曲线
    return min_val + (max_val - min_val) * (greenup - senescence)


def fit_vegetation_phenology(ts):
    """拟合植被物候曲线（年际趋势）"""
    # 按日聚合
    daily = ts.resample('D').mean()

    # 初始化参数
    years = daily.index.year.unique()
    full_phenology = pd.Series(np.nan, index=ts.index)

    for year in years:
        year_data = daily[daily.index.year == year]
        if len(year_data) < 100:  # 至少100天数据
            continue

        # 初始参数估计
        min_ndvi = year_data.min()
        max_ndvi = year_data.max()
        median_ndvi = year_data.median()

        # 找到生长季开始和结束
        sos_candidates = year_data[(year_data.index.dayofyear > 50) &
                                   (year_data.index.dayofyear < 200) &
                                   (year_data > (min_ndvi + 0.2 * (max_ndvi - min_ndvi)))]
        eos_candidates = year_data[(year_data.index.dayofyear > 200) &
                                   (year_data < (max_ndvi - 0.2 * (max_ndvi - min_ndvi)))]

        sos = sos_candidates.index.dayofyear.min() if not sos_candidates.empty else 120
        eos = eos_candidates.index.dayofyear.max() if not eos_candidates.empty else 280
        length = max(30, min(120, eos - sos))

        # 准备优化参数
        t = year_data.index.dayofyear.values
        y = year_data.values

        try:
            # 拟合双逻辑斯蒂曲线
            params, _ = curve_fit(
                double_logistic,
                t,
                y,
                p0=[sos, eos, length, max_ndvi, min_ndvi],
                bounds=([1, 150, 20, min_ndvi, min_ndvi * 0.8],
                        [200, 365, 150, max_ndvi * 1.2, max_ndvi])
            )

            # 生成全年预测
            year_days = np.arange(1, 367)
            year_phenology = double_logistic(year_days, *params)

            # 创建日期索引
            year_start = pd.Timestamp(f"{year}-01-01")
            year_dates = [year_start + pd.Timedelta(days=int(d) - 1) for d in year_days]

            # 插值到小时频率
            phenology_series = pd.Series(year_phenology, index=year_dates)
            phenology_series = phenology_series.resample('h').interpolate('linear')

            # 对齐原始时间索引
            year_mask = (ts.index.year == year)
            full_phenology[year_mask] = phenology_series.reindex(ts[year_mask].index, method='nearest')

        except Exception as e:
            logger.warning(f"无法拟合{year}年物候曲线: {str(e)}")
            # 使用平均值作为后备
            full_phenology[year_mask] = year_data.mean()

    return full_phenology


def extract_diurnal_component(ts, phenology):
    """提取时变日周期分量"""
    # 去除年际趋势
    detrended = ts - phenology

    # 按季节分组
    seasons = {
        'DJF': [12, 1, 2],  # 冬季
        'MAM': [3, 4, 5],  # 春季
        'JJA': [6, 7, 8],  # 夏季
        'SON': [9, 10, 11]  # 秋季
    }

    diurnal = pd.Series(np.nan, index=ts.index)
    diurnal_patterns = {}

    # 为每个季节计算日变化模式
    for season, months in seasons.items():
        # 选择季节数据
        season_mask = ts.index.month.isin(months)
        season_data = detrended[season_mask]

        if season_data.empty:
            continue

        # 按小时分组计算平均日变化
        hourly_avg = season_data.groupby(season_data.index.hour).mean()

        # 存储模式
        diurnal_patterns[season] = hourly_avg

        # 应用到时变日周期分量
        for hour in range(24):
            hour_mask = (ts.index.hour == hour) & season_mask
            diurnal[hour_mask] = hourly_avg[hour]

    # 插值处理缺失值
    diurnal = diurnal.interpolate(method='time')

    return diurnal, diurnal_patterns


def extract_residual(ts, phenology, diurnal):
    """提取高频残差信号（滞尘影响）"""
    # 计算残差
    residual = ts - phenology - diurnal

    # 应用高斯滤波保留高频信号
    from scipy.ndimage import gaussian_filter1d
    residual_smoothed = pd.Series(
        gaussian_filter1d(residual, sigma=3),
        index=residual.index
    )

    # 计算标准化残差
    residual_norm = (residual - residual_smoothed) / phenology

    return residual_norm


def vegetation_based_decomposition(ts):
    """
    基于植被物候学的分解方法
    返回:
        phenology: 年际物候趋势
        diurnal: 时变日周期分量
        residual: 高频残差信号（滞尘影响）
    """
    logger.info("开始植被物候学分解")

    # 步骤1: 拟合植被物候曲线
    logger.info("拟合植被物候曲线")
    phenology = fit_vegetation_phenology(ts)

    # 步骤2: 提取时变日周期分量
    logger.info("提取时变日周期分量")
    diurnal, diurnal_patterns = extract_diurnal_component(ts, phenology)

    # 步骤3: 提取高频残差信号
    logger.info("提取高频残差信号")
    residual = extract_residual(ts, phenology, diurnal)

    return {
        'phenology': phenology,
        'diurnal': diurnal,
        'residual': residual,
        'diurnal_patterns': diurnal_patterns
    }


def plot_components(station_id, ts, status_ts, components, output_dir):
    """绘制分解分量（科研优化版）"""
    station_output_dir = output_dir / station_id
    station_output_dir.mkdir(parents=True, exist_ok=True)

    # 1. 主分解图
    fig, axs = plt.subplots(4, 1, figsize=(12, 14), dpi=300)
    fig.suptitle(f'Vegetation Phenology Decomposition - Station {station_id}',
                 fontsize=16, fontname='Times New Roman', y=0.95)

    titles = ['Original NDVI', 'Phenology Trend', 'Diurnal Component', 'Residual (Dust Signal)']
    data_series = [ts, components['phenology'], components['diurnal'], components['residual']]

    for i, (title, data) in enumerate(zip(titles, data_series)):
        ax = axs[i]
        ax.plot(data.index, data, linewidth=1.0, color='#1f77b4')
        ax.set_title(title, fontname='Times New Roman', fontsize=12)
        ax.tick_params(axis='both', which='major', labelsize=9)

        # 科研风格优化
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['bottom'].set_linewidth(0.5)
        ax.spines['left'].set_linewidth(0.5)

        if i == len(axs) - 1:
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
            ax.tick_params(axis='x', rotation=45)

    # 在原始NDVI图上添加数据点标记
    valid_mask = (status_ts == 0)
    night_mask = (status_ts == -1)

    if valid_mask.any():
        axs[0].plot(ts.index[valid_mask], ts[valid_mask], '.',
                    markersize=2, color='#2ca02c', alpha=0.6, label='Valid Daytime')
    if night_mask.any():
        axs[0].plot(ts.index[night_mask], ts[night_mask], 'o',
                    markersize=2, color='#ff7f0e', alpha=0.6, label='Night Interpolated')
    if valid_mask.any() or night_mask.any():
        axs[0].legend(loc='best', frameon=False, fontsize=9)

    plt.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(station_output_dir / f"{station_id}_decomposition.png", dpi=300, bbox_inches='tight')

    # 2. 物候曲线图
    fig2, ax2 = plt.subplots(figsize=(10, 5), dpi=300)

    # 按年绘制物候曲线
    years = ts.index.year.unique()
    colors = plt.cm.viridis(np.linspace(0, 1, len(years)))

    for i, year in enumerate(years):
        year_mask = (ts.index.year == year)
        if not year_mask.any():
            continue

        ax2.plot(ts.index[year_mask].dayofyear,
                 components['phenology'][year_mask],
                 color=colors[i],
                 label=str(year))

    ax2.set_title(f'Phenology Trends - Station {station_id}',
                  fontname='Times New Roman', fontsize=12)
    ax2.set_xlabel('Day of Year', fontname='Times New Roman')
    ax2.set_ylabel('NDVI', fontname='Times New Roman')
    ax2.legend(title='Year', frameon=False)

    # 科研风格优化
    ax2.spines['top'].set_visible(False)
    ax2.spines['right'].set_visible(False)
    ax2.spines['bottom'].set_linewidth(0.5)
    ax2.spines['left'].set_linewidth(0.5)

    plt.tight_layout()
    fig2.savefig(station_output_dir / f"{station_id}_phenology.png", dpi=300, bbox_inches='tight')

    # 3. 日变化分量图（按季节）
    fig3, ax3 = plt.subplots(figsize=(10, 6), dpi=300)

    diurnal_patterns = components.get('diurnal_patterns', {})
    season_colors = {'DJF': '#1f77b4', 'MAM': '#2ca02c', 'JJA': '#d62728', 'SON': '#ff7f0e'}

    for season, pattern in diurnal_patterns.items():
        if pattern is not None:
            ax3.plot(pattern.index, pattern.values,
                     label=season,
                     color=season_colors.get(season, '#000000'),
                     linewidth=1.5)

    ax3.set_title(f'Seasonal Diurnal Patterns - Station {station_id}',
                  fontname='Times New Roman', fontsize=12)
    ax3.set_xlabel('Hour of Day', fontname='Times New Roman')
    ax3.set_ylabel('Diurnal Component', fontname='Times New Roman')
    ax3.set_xticks(range(0, 24, 2))
    ax3.legend(frameon=False)

    # 科研风格优化
    ax3.spines['top'].set_visible(False)
    ax3.spines['right'].set_visible(False)
    ax3.spines['bottom'].set_linewidth(0.5)
    ax3.spines['left'].set_linewidth(0.5)

    plt.tight_layout()
    fig3.savefig(station_output_dir / f"{station_id}_diurnal_seasonal.png", dpi=300, bbox_inches='tight')

    plt.close('all')
    logger.info(f"站点 {station_id} 的分解图表已保存")


def process_station(station_file, output_dir):
    """处理单个站点的分解"""
    station_id = station_file.stem.split('_')[-1]

    try:
        with xr.open_dataset(station_file) as ds:
            time_index = ds['time'].values
            ndvi_series = ds['NDVI'].values
            status_series = ds['status'].values

        # 准备时间序列数据
        ts, status_ts = prepare_station_data(ndvi_series, status_series, time_index)

        # 执行植被物候学分解
        components = vegetation_based_decomposition(ts)

        # 绘制分量图表
        plot_components(station_id, ts, status_ts, components, output_dir)

        return True
    except Exception as e:
        logger.error(f"处理站点 {station_id} 时出错: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def main():
    """主函数：并行处理站点"""
    output_dir = Path(OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 获取所有站点文件
    station_files = list(Path(INPUT_DIR).glob("NDVI_Station_*.nc"))

    if not station_files:
        logger.error(f"在目录 {INPUT_DIR} 中未找到任何站点文件")
        return

    logger.info(f"找到 {len(station_files)} 个站点文件")

    # 并行处理
    max_workers = min(8, os.cpu_count())
    processed = 0
    skipped = 0
    futures = []

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        for station_file in station_files:
            station_id = station_file.stem.split('_')[-1]
            station_output_dir = output_dir / station_id

            # 检查是否已处理
            if station_output_dir.exists():
                plot_files = [
                    station_output_dir / f"{station_id}_decomposition.png",
                    station_output_dir / f"{station_id}_phenology.png",
                    station_output_dir / f"{station_id}_diurnal_seasonal.png"
                ]

                if all(f.exists() for f in plot_files):
                    logger.info(f"站点 {station_id} 的分解结果已存在，跳过")
                    skipped += 1
                    continue

            # 提交任务
            future = executor.submit(process_station, station_file, output_dir)
            futures.append(future)

        # 处理结果
        for future in as_completed(futures):
            try:
                if future.result():
                    processed += 1
                    logger.info(f"站点处理成功")
                else:
                    logger.error(f"站点处理失败")
            except Exception as e:
                logger.error(f"站点处理出错: {str(e)}")

    logger.info(f"处理完成! 成功处理 {processed} 个站点, 跳过 {skipped} 个站点")


if __name__ == "__main__":
    main()