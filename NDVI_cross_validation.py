import os
import netCDF4 as nc
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime, timedelta
from tqdm import tqdm
from sklearn.metrics import r2_score, mean_squared_error
from scipy.stats import gaussian_kde
import calendar
import xarray as xr
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing as mp
import glob
import warnings
import argparse

# 忽略特定警告
warnings.filterwarnings("ignore", category=UserWarning, message="Warning: converting a masked element to nan.")

# ======================== 配置参数 ========================
START_DATE = '20150707'
END_DATE = '20151231'
POI_NC_FILE = 'D:/H8_data/LUTs.nc'
SOZSR_DIR = 'D:/H8_data/Hourly_sozSR_Angles'
H8SR_DIR = 'D:/H8_data/H8SR'
MODIS_DIR = 'D:/H8_Data/MODIS_NDVI'
STATION_TS_DIR = f'D:/H8_Data/NDVI_cross_validation/Station_TimeSeries_{START_DATE}_{END_DATE}'  # 带日期范围的目录
OUTPUT_DIR = f'D:/H8_Data/NDVI_cross_validation/output_plots_{START_DATE}_{END_DATE}'
DEPRECATED_STATIONS_FILE = 'D:/H8_data/Station_deprecated.nc'

# 创建输出目录
os.makedirs(STATION_TS_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 并行处理参数
MAX_WORKERS = max(1, mp.cpu_count() - 2)
BATCH_SIZE = 30  # 处理站点的批次大小


# ======================== 工具函数 ========================
def get_deprecated_stations():
    """获取废弃站点列表"""
    try:
        with nc.Dataset(DEPRECATED_STATIONS_FILE) as ds:
            stations = ds.variables['Station'][:]
            return [''.join(s).strip() for s in stations]
    except Exception as e:
        print(f"读取废弃站点文件时出错: {e}")
        return []


def load_poi_list():
    """从NetCDF文件加载POI列表"""
    try:
        with nc.Dataset(POI_NC_FILE) as ds:
            stations = ds.variables['Station'][:]
            return [''.join(s).strip() for s in stations]
    except Exception as e:
        print(f"读取POI列表文件时出错: {e}")
        return []


def parse_date_range(start_date, end_date):
    """解析日期范围，返回日期对象列表"""
    start = datetime.strptime(start_date, '%Y%m%d')
    end = datetime.strptime(end_date, '%Y%m%d')
    delta = end - start
    return [start + timedelta(days=i) for i in range(delta.days + 1)]


# ======================== 阶段1: 重组站点时间序列 ========================
def extract_modis_data_for_station(date_obj, station_name):
    """为单个站点提取单日MODIS数据"""
    date_str = date_obj.strftime('%Y%m%d')
    year = date_str[:4]
    month = date_str[4:6]
    file_path = os.path.join(MODIS_DIR, year, month, f'MODIS_NDVI_{date_str}.nc')

    if not os.path.exists(file_path):
        return np.nan, np.nan

    try:
        with nc.Dataset(file_path) as ds:
            stations = ds.variables['Station'][:]
            station_names = [''.join(s).strip() for s in stations]

            if station_name not in station_names:
                return np.nan, np.nan

            idx = station_names.index(station_name)
            terra_ndvi = ds.variables['NDVI_Terra'][idx]
            aqua_ndvi = ds.variables['NDVI_Aqua'][idx]

            # 处理缺失值
            terra_ndvi = np.nan if terra_ndvi in [-9999.0, None] else float(terra_ndvi)
            aqua_ndvi = np.nan if aqua_ndvi in [-9999.0, None] else float(aqua_ndvi)

            return terra_ndvi, aqua_ndvi
    except Exception as e:
        print(f"读取MODIS数据时出错: {e}")
        return np.nan, np.nan


def extract_h8_data_for_station(date_obj, station_name, data_type):
    """为单个站点提取单日Himawari-8数据"""
    date_str = date_obj.strftime('%Y%m%d')
    prev_date = (date_obj - timedelta(days=1)).strftime('%Y%m%d')

    # 确定数据目录
    data_dir = SOZSR_DIR if data_type == 'soz' else H8SR_DIR

    # 目标时间点（北京时间10:00和13:00）
    target_times = [10, 13]
    ndvi_values = {t: np.nan for t in target_times}

    # 检查前一天21-23时和当天0-18时
    time_ranges = [
        (prev_date, [21, 22, 23]),
        (date_str, list(range(0, 19)))
    ]

    for date_prefix, hours in time_ranges:
        for hh in hours:
            hour_str = str(hh).zfill(2)

            if data_type == 'soz':
                file_path = os.path.join(
                    data_dir, date_prefix[:4], date_prefix[4:6],
                    f'H8_hourly_sozSR_angles_{date_prefix}_{hour_str}00.nc'
                )
            else:
                # 尝试两种文件路径结构
                file_path1 = os.path.join(data_dir, f'SR_{date_prefix}_{hour_str}00.nc')
                file_path2 = os.path.join(data_dir, date_prefix[:4], date_prefix[4:6],
                                          f'SR_{date_prefix}_{hour_str}00.nc')

                file_path = file_path1 if os.path.exists(file_path1) else file_path2

            if not os.path.exists(file_path):
                continue

            try:
                with nc.Dataset(file_path) as ds:
                    # 获取站点列表
                    stations = ds.variables['Station'][:]
                    station_names = [''.join(s).strip() for s in stations]

                    if station_name not in station_names:
                        continue

                    idx = station_names.index(station_name)

                    # 检查数据可用性（仅soz需要）
                    if data_type == 'soz':
                        avail_var = ds.variables.get('hourly_availability')
                        if avail_var is not None:
                            avail = avail_var[idx]
                            if avail != 0:  # 0表示有效数据
                                continue

                    # 计算NDVI
                    b3 = ds.variables['Albedo_03'][idx]
                    b4 = ds.variables['Albedo_04'][idx]
                    denom = b4 + b3

                    if denom <= 0.01:
                        continue

                    ndvi = (b4 - b3) / denom
                    if np.isnan(ndvi) or ndvi < -1 or ndvi > 1:
                        continue

                    # 转换为北京时间 (UTC+8)
                    utc_time = datetime.strptime(f"{date_prefix}{hour_str}", '%Y%m%d%H')
                    bj_time = utc_time + timedelta(hours=8)

                    # 仅保留目标时间点附近数据（±30分钟）
                    for target in target_times:
                        target_dt = datetime(bj_time.year, bj_time.month, bj_time.day, target)
                        time_diff = abs((bj_time - target_dt).total_seconds() / 3600)

                        if time_diff <= 0.5:  # 30分钟内
                            # 如果已有数据，保留时间更接近的数据
                            if np.isnan(ndvi_values[target]) or time_diff < abs(
                                    (bj_time - target_dt).total_seconds() / 3600):
                                ndvi_values[target] = ndvi
            except Exception as e:
                print(f"处理文件 {os.path.basename(file_path)} 时出错: {str(e)}")
                continue

    return ndvi_values[10], ndvi_values[13]


def station_needs_processing(station_file):
    """检查站点是否需要重新处理"""
    if not os.path.exists(station_file):
        return True

    try:
        with xr.open_dataset(station_file) as ds:
            # 检查日期范围属性
            if 'start_date' not in ds.attrs or 'end_date' not in ds.attrs:
                return True

            if ds.attrs['start_date'] != START_DATE or ds.attrs['end_date'] != END_DATE:
                return True

            # 检查时间维度
            time_coords = ds.coords['time'].values
            expected_dates = parse_date_range(START_DATE, END_DATE)
            if len(time_coords) != len(expected_dates):
                return True

            return False
    except:
        return True


def process_single_station(station_name, date_objs):
    """处理单个站点的时间序列数据"""
    station_file = os.path.join(STATION_TS_DIR, f"Station_{station_name}.nc")

    # 检查是否需要处理
    if not station_needs_processing(station_file):
        print(f"站点 {station_name} 已存在且数据完整，跳过处理")
        return station_name

    print(f"开始处理站点: {station_name}")

    # 准备数据结构
    times = []
    terra_ndvi = []
    aqua_ndvi = []
    soz_10 = []
    soz_13 = []
    h8sr_10 = []
    h8sr_13 = []

    # 处理每一天
    for date_obj in date_objs:
        # 提取MODIS数据
        t_ndvi, a_ndvi = extract_modis_data_for_station(date_obj, station_name)

        # 提取H8数据
        s10, s13 = extract_h8_data_for_station(date_obj, station_name, 'soz')
        h10, h13 = extract_h8_data_for_station(date_obj, station_name, '6s')

        # 保存数据
        times.append(date_obj)
        terra_ndvi.append(t_ndvi)
        aqua_ndvi.append(a_ndvi)
        soz_10.append(s10)
        soz_13.append(s13)
        h8sr_10.append(h10)
        h8sr_13.append(h13)

    # 创建数据集
    ds = xr.Dataset(
        {
            "NDVI_Terra": (("time",), np.array(terra_ndvi, dtype=np.float32)),
            "NDVI_Aqua": (("time",), np.array(aqua_ndvi, dtype=np.float32)),
            "NDVI_soz_10": (("time",), np.array(soz_10, dtype=np.float32)),
            "NDVI_soz_13": (("time",), np.array(soz_13, dtype=np.float32)),
            "NDVI_6s_10": (("time",), np.array(h8sr_10, dtype=np.float32)),
            "NDVI_6s_13": (("time",), np.array(h8sr_13, dtype=np.float32))
        },
        coords={"time": np.array(times)}
    )

    # 添加属性
    ds.attrs = {
        "station_name": station_name,
        "start_date": START_DATE,
        "end_date": END_DATE,
        "creation_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    # 保存为NetCDF
    ds.to_netcdf(station_file)
    print(f"站点 {station_name} 处理完成")
    return station_name


def run_stage1():
    """运行阶段1：重组站点时间序列数据"""
    print("====== 开始阶段1：重组站点时间序列数据 ======")
    print(f"时间范围: {START_DATE} 到 {END_DATE}")
    print(f"输出目录: {STATION_TS_DIR}")

    # 获取POI列表和废弃站点
    poi_list = load_poi_list()
    deprecated_list = get_deprecated_stations()

    # 过滤掉废弃站点
    valid_stations = [s for s in poi_list if s not in deprecated_list]
    print(f"找到 {len(poi_list)} 个POI, 其中 {len(valid_stations)} 个有效站点")

    # 解析日期范围
    date_objs = parse_date_range(START_DATE, END_DATE)
    print(f"共 {len(date_objs)} 天数据")

    # 并行处理站点
    completed_stations = []
    with ProcessPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = []

        # 检查并只提交需要处理的站点
        stations_to_process = []
        for station in valid_stations:
            station_file = os.path.join(STATION_TS_DIR, f"Station_{station}.nc")
            if station_needs_processing(station_file):
                stations_to_process.append(station)

        print(f"需要处理的站点数量: {len(stations_to_process)}")

        # 分批提交任务
        for i in range(0, len(stations_to_process), BATCH_SIZE):
            batch = stations_to_process[i:i + BATCH_SIZE]
            for station in batch:
                future = executor.submit(process_single_station, station, date_objs)
                futures.append(future)

        # 处理完成的任务
        for future in tqdm(as_completed(futures), total=len(futures), desc="处理站点"):
            try:
                station_name = future.result()
                completed_stations.append(station_name)
            except Exception as e:
                print(f"处理站点时出错: {str(e)}")

    print(f"阶段1完成! 已处理 {len(completed_stations)} 个站点")

# ======================== 阶段2: 交叉验证分析 ========================
def load_station_data(station_name):
    """加载单个站点的重组数据"""
    station_file = os.path.join(STATION_TS_DIR, f"Station_{station_name}.nc")
    if not os.path.exists(station_file):
        return pd.DataFrame()

    try:
        ds = xr.open_dataset(station_file)
        df = ds.to_dataframe().reset_index()
        df['station'] = station_name
        return df
    except Exception as e:
        print(f"加载站点 {station_name} 数据时出错: {str(e)}")
        return pd.DataFrame()


def safe_r2_score(y_true, y_pred):
    """安全的R²计算函数，处理小样本情况"""
    if len(y_true) < 2:
        return np.nan

    try:
        return r2_score(y_true, y_pred)
    except Exception:
        return np.nan


def plot_density_scatter(x, y, xlabel, ylabel):
    """绘制带密度和统计信息的散点图"""
    # 移除NaN值
    valid_idx = ~np.isnan(x) & ~np.isnan(y)
    x_vals = x[valid_idx].values  # 转换为numpy数组
    y_vals = y[valid_idx].values  # 转换为numpy数组

    if len(x_vals) < 2:
        plt.text(0.5, 0.5, "数据不足", ha='center', va='center')
        plt.xlabel(xlabel)
        plt.ylabel(ylabel)
        return

    # 计算密度
    xy = np.vstack([x_vals, y_vals])
    z = gaussian_kde(xy)(xy)

    # 排序以便高密度点最后绘制
    idx = z.argsort()
    x_vals, y_vals, z = x_vals[idx], y_vals[idx], z[idx]

    # 创建散点图
    plt.scatter(x_vals, y_vals, c=z, s=10, alpha=0.5, cmap='viridis')

    # 添加1:1线
    max_val = max(np.nanmax(x_vals), np.nanmax(y_vals))
    min_val = min(np.nanmin(x_vals), np.nanmin(y_vals))
    plt.plot([min_val, max_val], [min_val, max_val], 'r--', alpha=0.7)

    # 添加统计信息
    r2 = r2_score(x_vals, y_vals)
    rmse = np.sqrt(mean_squared_error(x_vals, y_vals))
    bias = np.mean(y_vals - x_vals)

    plt.text(0.05, 0.95, f'R² = {r2:.3f}\nRMSE = {rmse:.3f}\nBias = {bias:.3f}\nn = {len(x_vals)}',
             transform=plt.gca().transAxes, verticalalignment='top',
             bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))

    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.grid(True, alpha=0.3)
    plt.colorbar(label='Dot density')


def generate_comparison_plots(full_df):
    """生成交叉验证图表"""
    # 创建副本避免SettingWithCopyWarning
    df = full_df.copy()

    # 过滤有效数据点
    df = df.dropna(subset=['NDVI_modis', 'NDVI_6s', 'NDVI_soz'], how='all')

    if df.empty:
        print("没有足够数据生成图表")
        return

    # 1. 整体散点密度图
    plt.figure(figsize=(16, 8))

    plt.subplot(121)
    plot_density_scatter(df['NDVI_modis'], df['NDVI_6s'], 'MODIS NDVI', 'Himawari-8 NDVI (6S+BRDF)')
    plt.title('NDVI_6s vs NDVI_modis', fontsize=14)

    plt.subplot(122)
    plot_density_scatter(df['NDVI_modis'], df['NDVI_soz'], 'MODIS NDVI', 'Himawari-8 NDVI (Solar Angle)')
    plt.title('NDVI_soz vs NDVI_modis', fontsize=14)

    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, 'NDVI_CrossValidation_ScatterDensity.png'), dpi=300)
    plt.close()

    # 2. 误差分布图
    df['error_6s'] = df['NDVI_6s'] - df['NDVI_modis']
    df['error_soz'] = df['NDVI_soz'] - df['NDVI_modis']

    plt.figure(figsize=(12, 8))
    sns.kdeplot(data=df, x='error_6s', label='6S+BRDF', fill=True, alpha=0.5)
    sns.kdeplot(data=df, x='error_soz', label='Solar Angle', fill=True, alpha=0.5)
    plt.axvline(x=0, color='gray', linestyle='--')
    plt.xlabel('NDVI Difference (Himawari-8 - MODIS)')
    plt.ylabel('Density')
    plt.title('Comparison of error distribution')
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.savefig(os.path.join(OUTPUT_DIR, 'NDVI_Error_Distribution.png'), dpi=300)
    plt.close()

    # 3. 时间序列分析（按年）
    df['date'] = pd.to_datetime(df['date'])
    df['year'] = df['date'].dt.year
    yearly_metrics = df.groupby('year').agg({
        'error_6s': ['mean', 'std'],
        'error_soz': ['mean', 'std']
    }).reset_index()

    if not yearly_metrics.empty:
        plt.figure(figsize=(12, 8))
        plt.errorbar(yearly_metrics['year'], yearly_metrics[('error_6s', 'mean')],
                     yerr=yearly_metrics[('error_6s', 'std')],
                     label='6S+BRDF', fmt='-o', capsize=5)
        plt.errorbar(yearly_metrics['year'], yearly_metrics[('error_soz', 'mean')],
                     yerr=yearly_metrics[('error_soz', 'std')],
                     label='Solar Angle', fmt='-s', capsize=5)
        plt.axhline(y=0, color='gray', linestyle='--')
        plt.xlabel('year')
        plt.ylabel('Mean Error (Himawari-8 - MODIS)')
        plt.title('annual NDVI compared of MODIS')
        plt.legend()
        plt.grid(True, alpha=0.3)
        plt.savefig(os.path.join(OUTPUT_DIR, 'NDVI_Annual_Comparison.png'), dpi=300)
        plt.close()

    # 4. 按时间段分析（上午 vs 下午）
    time_metrics = df.groupby('time').agg({
        'error_6s': ['mean', 'std'],
        'error_soz': ['mean', 'std']
    }).reset_index()

    if not time_metrics.empty:
        plt.figure(figsize=(10, 6))
        x = np.arange(len(time_metrics))
        width = 0.35

        plt.bar(x - width / 2, time_metrics[('error_6s', 'mean')], width,
                yerr=time_metrics[('error_6s', 'std')], label='6S+BRDF', capsize=5)
        plt.bar(x + width / 2, time_metrics[('error_soz', 'mean')], width,
                yerr=time_metrics[('error_soz', 'std')], label='Solar Angle', capsize=5)

        plt.axhline(y=0, color='gray', linestyle='--')
        plt.xlabel('Time')
        plt.ylabel('Mean error (Himawari-8 - MODIS)')
        plt.title('NDVI time series comparison')
        plt.xticks(x, time_metrics['time'])
        plt.legend()
        plt.grid(axis='y', alpha=0.3)
        plt.tight_layout()
        plt.savefig(os.path.join(OUTPUT_DIR, 'NDVI_TimeOfDay_Comparison.png'), dpi=300)
        plt.close()

    # 5. 季节分析 - 鲁棒版本
    df['month'] = df['date'].dt.month

    # 定义季节映射
    season_map = {
        12: 'Winter', 1: 'Winter', 2: 'Winter',
        3: 'Spring', 4: 'Spring', 5: 'Spring',
        6: 'Summer', 7: 'Summer', 8: 'Summer',
        9: 'Autumn', 10: 'Autumn', 11: 'Autumn'
    }

    # 安全应用季节映射
    df['season'] = df['month'].map(season_map)

    # 分组统计
    seasonal_metrics = df.groupby('season').agg({
        'error_6s': ['mean', 'std'],
        'error_soz': ['mean', 'std']
    }).reset_index()

    # 定义季节顺序
    season_order = ['Spring', 'Summer', 'Autumn', 'Winter']

    # 按季节顺序排序
    seasonal_metrics['season'] = pd.Categorical(
        seasonal_metrics['season'],
        categories=season_order,
        ordered=True
    )
    seasonal_metrics = seasonal_metrics.sort_values('season')

    if not seasonal_metrics.empty:
        plt.figure(figsize=(12, 8))
        x = np.arange(len(seasonal_metrics))
        width = 0.35

        # 提取平均值和标准差
        mean_6s = seasonal_metrics[('error_6s', 'mean')].values
        std_6s = seasonal_metrics[('error_6s', 'std')].values
        mean_soz = seasonal_metrics[('error_soz', 'mean')].values
        std_soz = seasonal_metrics[('error_soz', 'std')].values

        plt.bar(x - width / 2, mean_6s, width, yerr=std_6s, label='6S+BRDF', capsize=5)
        plt.bar(x + width / 2, mean_soz, width, yerr=std_soz, label='Solar Angle', capsize=5)

        plt.axhline(y=0, color='gray', linestyle='--')
        plt.xlabel('Season')
        plt.ylabel('Mean error (Himawari-8 - MODIS)')
        plt.title('NDVI time series comparison')
        plt.xticks(x, seasonal_metrics['season'])
        plt.legend()
        plt.grid(axis='y', alpha=0.3)
        plt.tight_layout()
        plt.savefig(os.path.join(OUTPUT_DIR, 'NDVI_Seasonal_Comparison.png'), dpi=300)
        plt.close()

    # 6. 统计指标表
    # 安全的指标计算
    def calculate_metrics(true, pred):
        valid_idx = ~np.isnan(true) & ~np.isnan(pred)
        true = true[valid_idx]
        pred = pred[valid_idx]

        if len(true) < 2:
            return {
                'r2': np.nan,
                'rmse': np.nan,
                'bias': np.nan,
                'slope': np.nan,
                'count': len(true)
            }

        return {
            'r2': r2_score(true, pred),
            'rmse': np.sqrt(mean_squared_error(true, pred)),
            'bias': np.mean(pred - true),
            'slope': np.polyfit(true, pred, 1)[0],
            'count': len(true)
        }

    metrics_6s = calculate_metrics(df['NDVI_modis'], df['NDVI_6s'])
    metrics_soz = calculate_metrics(df['NDVI_modis'], df['NDVI_soz'])

    stats_table = pd.DataFrame({
        'Indicators': ['R²', 'RMSE', 'bias', 'slope', 'n'],
        '6S+BRDF': [
            metrics_6s['r2'],
            metrics_6s['rmse'],
            metrics_6s['bias'],
            metrics_6s['slope'],
            metrics_6s['count']
        ],
        'Solar Angle adjusted': [
            metrics_soz['r2'],
            metrics_soz['rmse'],
            metrics_soz['bias'],
            metrics_soz['slope'],
            metrics_soz['count']
        ]
    })

    stats_table.to_csv(os.path.join(OUTPUT_DIR, 'NDVI_Validation_Metrics.csv'), index=False)

    fig, ax = plt.subplots(figsize=(12, 4))
    ax.axis('off')
    table = ax.table(
        cellText=stats_table.values,
        colLabels=stats_table.columns,
        cellLoc='center',
        loc='center',
        bbox=[0, 0, 1, 1]
    )
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1.2, 1.2)
    plt.title('Summary of NDVI Validation', fontsize=14, pad=20)
    plt.savefig(os.path.join(OUTPUT_DIR, 'NDVI_Validation_Metrics.png'), dpi=300, bbox_inches='tight')
    plt.close()


def run_stage2():
    """运行阶段2：交叉验证分析"""
    print("====== 开始阶段2：交叉验证分析 ======")

    # 获取所有站点文件
    station_files = glob.glob(os.path.join(STATION_TS_DIR, "Station_*.nc"))
    if not station_files:
        print("未找到任何站点数据文件，请先运行阶段1")
        return

    print(f"找到 {len(station_files)} 个站点数据文件")

    # 加载所有站点数据
    all_data = []
    for file_path in tqdm(station_files, desc="加载站点数据"):
        try:
            ds = xr.open_dataset(file_path)
            df = ds.to_dataframe().reset_index()

            # 从文件名获取站点名
            station_name = os.path.basename(file_path).split('_')[1].split('.')[0]
            df['station'] = station_name

            # 重组数据格式
            # 10:00 时间点 - 使用Terra数据
            df_10 = df[['time', 'NDVI_Terra', 'NDVI_soz_10', 'NDVI_6s_10', 'station']].copy()
            df_10.columns = ['date', 'NDVI_modis', 'NDVI_soz', 'NDVI_6s', 'station']
            df_10['time'] = '10:00'

            # 13:00 时间点 - 使用Aqua数据
            df_13 = df[['time', 'NDVI_Aqua', 'NDVI_soz_13', 'NDVI_6s_13', 'station']].copy()
            df_13.columns = ['date', 'NDVI_modis', 'NDVI_soz', 'NDVI_6s', 'station']
            df_13['time'] = '13:00'

            # 合并
            station_df = pd.concat([df_10, df_13])
            all_data.append(station_df)
        except Exception as e:
            print(f"加载文件 {file_path} 时出错: {str(e)}")

    if not all_data:
        print("未加载到任何有效数据")
        return

    full_df = pd.concat(all_data, ignore_index=True)

    # 保存处理后的数据
    full_file = os.path.join(OUTPUT_DIR, 'NDVI_CrossValidation_Full_Data.csv')
    full_df.to_csv(full_file, index=False)
    print(f"完整数据已保存: {full_file}")

    # 生成图表
    print("生成交叉验证图表...")
    generate_comparison_plots(full_df)
    print("图表生成完成!")


# ======================== 主函数 ========================
def main_menu():
    """显示主菜单并处理用户选择"""
    while True:
        print("\n====== NDVI交叉验证分析 ======")
        print("1: 重组站点时间序列")
        print("2: 交叉验证分析")
        print("q: 退出程序")

        choice = input("请选择操作 (1/2/q): ").strip().lower()

        if choice == '1':
            run_stage1()
        elif choice == '2':
            run_stage2()
        elif choice == 'q':
            print("程序已退出")
            break
        else:
            print("无效选择，请重新输入")


if __name__ == "__main__":
    main_menu()