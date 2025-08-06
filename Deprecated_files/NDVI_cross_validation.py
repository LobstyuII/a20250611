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
END_DATE = '20180707'
POI_NC_FILE = 'D:/H8_data/LUTs.nc'
SOZSR_DIR = 'D:/H8_data/Hourly_sozSR_Angles'
H8SR_DIR = 'D:/H8_data/H8SR'
MOD09GA_DIR = 'D:/H8_Data/MODIS_NDVI'  # MOD/MYD09GA数据目录
MOD13A1_DIR = 'D:/H8_Data/MODIS_NDVI_MOD13A1'  # MOD13A1数据目录
MOD43A4_DIR = 'D:/H8_Data/MODIS_NDVI_nadir'  # MOD43A4数据目录
DEPRECATED_STATIONS_FILE = 'D:/H8_data/Station_deprecated.nc'

# 修改输出目录
STATION_TS_DIR = f'D:/H8_Data/NDVI_cross_validation/Station_TimeSeries_{START_DATE}_{END_DATE}'  # 带日期范围的目录
OUTPUT_DIR = f'D:/H8_Data/NDVI_cross_validation/output_plots_{START_DATE}_{END_DATE}'

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
def extract_modis_data_for_station(date_obj, station_name, data_source):
    """为单个站点提取单日MODIS数据"""
    date_str = date_obj.strftime('%Y%m%d')
    year = date_str[:4]
    month = date_str[4:6]

    if data_source == 'MOD09GA':
        file_path = os.path.join(MOD09GA_DIR, year, month, f'MODIS_NDVI_{date_str}.nc')
    elif data_source == 'MOD13A1':  # 修改为elif
        file_path = os.path.join(MOD13A1_DIR, year, month, f'MOD13A1_NDVI_{date_str}.nc')
    elif data_source == 'MOD43A4':  # 添加MOD43A4分支
        file_path = os.path.join(MOD43A4_DIR, year, month, f'MODIS_NDVI_nadir_{date_str}.nc')
    else:
        raise ValueError(f"未知数据源: {data_source}")

    if not os.path.exists(file_path):
        return np.nan

    try:
        with nc.Dataset(file_path) as ds:
            stations = ds.variables['Station'][:]
            station_names = [''.join(s).strip() for s in stations]

            if station_name not in station_names:
                return np.nan

            idx = station_names.index(station_name)

            if data_source == 'MOD09GA':
                terra_ndvi = ds.variables['NDVI_Terra'][idx]
                aqua_ndvi = ds.variables['NDVI_Aqua'][idx]

                # 处理缺失值并计算平均值
                if terra_ndvi in [-9999.0, None] or np.isnan(terra_ndvi):
                    terra_ndvi = np.nan
                else:
                    terra_ndvi = float(terra_ndvi)

                if aqua_ndvi in [-9999.0, None] or np.isnan(aqua_ndvi):
                    aqua_ndvi = np.nan
                else:
                    aqua_ndvi = float(aqua_ndvi)

                # 如果两个值都存在，计算平均值；否则返回存在的值
                if not np.isnan(terra_ndvi) and not np.isnan(aqua_ndvi):
                    return (terra_ndvi + aqua_ndvi) / 2
                elif not np.isnan(terra_ndvi):
                    return terra_ndvi
                elif not np.isnan(aqua_ndvi):
                    return aqua_ndvi
                else:
                    return np.nan
            elif data_source == 'MOD13A1':
                ndvi = ds.variables['NDVI_MOD13A1'][idx]
                if ndvi in [-9999.0, None] or np.isnan(ndvi):
                    return np.nan
                return float(ndvi)
            else:  # MOD43A4
                ndvi = ds.variables['NDVI_nadir'][idx]
                if ndvi in [-9999.0, None] or np.isnan(ndvi):
                    return np.nan
                return float(ndvi)
    except Exception as e:
        print(f"读取{data_source}数据时出错: {e}")
        return np.nan


def extract_h8_data_for_station(date_obj, station_name, data_type):
    """为单个站点提取单日Himawari-8数据，返回全天平均值"""
    date_str = date_obj.strftime('%Y%m%d')
    prev_date = (date_obj - timedelta(days=1)).strftime('%Y%m%d')

    # 确定数据目录
    data_dir = SOZSR_DIR if data_type == 'soz' else H8SR_DIR

    # 存储所有有效NDVI值
    all_ndvi = []

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
                file_path1 = os.path.join(data_dir, f'H8SR_{date_prefix}_{hour_str}00.nc')
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

                    # 检查是否为NaN值
                    if np.isnan(b3) or np.isnan(b4):
                        continue

                    denom = b4 + b3

                    # 检查分母是否过小（避免除以零）
                    if denom <= 0.01:
                        continue

                    ndvi = (b4 - b3) / denom

                    # 检查NDVI是否有效
                    if np.isnan(ndvi) or ndvi < -1 or ndvi > 1:
                        continue

                    all_ndvi.append(ndvi)
            except Exception as e:
                # print(f"处理文件 {os.path.basename(file_path)} 时出错: {str(e)}")
                continue

    # 计算全天平均值
    if all_ndvi:
        return np.mean(all_ndvi)
    else:
        return np.nan


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
        # print(f"站点 {station_name} 已存在且数据完整，跳过处理")
        return station_name

    # 准备数据结构
    times = []
    mod09ga_ndvi = []
    mod13a1_ndvi = []
    mod43a4_ndvi = []
    soz_avg = []
    h8sr_avg = []

    # 处理每一天
    for date_obj in date_objs:
        # 提取两种MODIS数据
        mod09ga_ndvi.append(extract_modis_data_for_station(date_obj, station_name, 'MOD09GA'))
        mod13a1_ndvi.append(extract_modis_data_for_station(date_obj, station_name, 'MOD13A1'))
        mod43a4_ndvi.append(extract_modis_data_for_station(date_obj, station_name, 'MOD43A4'))

        # 提取H8数据
        soz_avg.append(extract_h8_data_for_station(date_obj, station_name, 'soz'))
        h8sr_avg.append(extract_h8_data_for_station(date_obj, station_name, '6s'))

        times.append(date_obj)

    # 创建数据集
    ds = xr.Dataset(
        {
            "NDVI_MOD09GA": (("time",), np.array(mod09ga_ndvi, dtype=np.float32)),
            "NDVI_MOD13A1": (("time",), np.array(mod13a1_ndvi, dtype=np.float32)),
            "NDVI_MOD43A4": (("time",), np.array(mod43a4_ndvi, dtype=np.float32)),
            "NDVI_soz": (("time",), np.array(soz_avg, dtype=np.float32)),
            "NDVI_6s": (("time",), np.array(h8sr_avg, dtype=np.float32))
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


def plot_density_scatter(ax, x, y, xlabel, ylabel, title, color):
    """绘制带密度和统计信息的散点图到指定axes"""
    # 移除NaN值
    valid_idx = ~np.isnan(x) & ~np.isnan(y)
    x_vals = x[valid_idx].values
    y_vals = y[valid_idx].values

    if len(x_vals) < 2:
        ax.text(0.5, 0.5, "数据不足", ha='center', va='center')
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        return

    # 计算密度
    xy = np.vstack([x_vals, y_vals])
    z = gaussian_kde(xy)(xy)

    # 排序以便高密度点最后绘制
    idx = z.argsort()
    x_vals, y_vals, z = x_vals[idx], y_vals[idx], z[idx]

    # 创建散点图
    scatter = ax.scatter(x_vals, y_vals, c=z, s=10, alpha=0.5, cmap='viridis')

    # 添加1:1线
    max_val = max(np.nanmax(x_vals), np.nanmax(y_vals))
    min_val = min(np.nanmin(x_vals), np.nanmin(y_vals))
    ax.plot([min_val, max_val], [min_val, max_val], 'r--', alpha=0.7, label='1:1 Line')

    # 计算皮尔逊相关系数
    pearson_r = np.corrcoef(x_vals, y_vals)[0, 1]
    r2 = pearson_r ** 2

    # 计算线性回归拟合线
    slope, intercept = np.polyfit(x_vals, y_vals, 1)
    fit_x = np.array([min_val, max_val])
    fit_y = slope * fit_x + intercept
    ax.plot(fit_x, fit_y, 'b-', alpha=0.7, label='Regression Line')

    # 添加统计信息
    rmse = np.sqrt(mean_squared_error(x_vals, y_vals))
    bias = np.mean(y_vals - x_vals)

    ax.text(0.05, 0.95, f'R² = {r2:.3f}\nRMSE = {rmse:.3f}\nBias = {bias:.3f}\nn = {len(x_vals)}',
            transform=ax.transAxes, verticalalignment='top',
            bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))

    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    ax.legend(loc='lower right')
    return scatter


# 在 generate_comparison_plots 函数中更新 calculate_metrics 函数
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

    # 计算皮尔逊相关系数的平方
    pearson_r = np.corrcoef(true, pred)[0, 1]
    r2 = pearson_r ** 2

    return {
        'r2': r2,
        'rmse': np.sqrt(mean_squared_error(true, pred)),
        'bias': np.mean(pred - true),
        'slope': np.polyfit(true, pred, 1)[0],
        'count': len(true)
    }


def generate_comparison_plots(full_df):
    """生成交叉验证图表"""
    df = full_df.copy()

    # 检查列是否存在
    required_columns = ['NDVI_MOD09GA', 'NDVI_MOD13A1', 'NDVI_6s', 'NDVI_soz']
    available_columns = [col for col in required_columns if col in df.columns]

    if not available_columns:
        print("没有找到必要的NDVI列，无法生成图表")
        return

    # 过滤有效数据点
    df = df.dropna(subset=available_columns, how='all')

    if df.empty:
        print("没有足够数据生成图表")
        return

    # 1. 整体散点密度图 - 在同一图上显示两种MODIS数据
    fig, axes = plt.subplots(3, 2, figsize=(16, 21))

    # 第一排: MOD09GA比较
    if 'NDVI_MOD09GA' in df.columns and 'NDVI_6s' in df.columns:
        plot_density_scatter(axes[0, 0], df['NDVI_MOD09GA'], df['NDVI_6s'],
                             'MODIS MOD09GA NDVI', 'Himawari-8 NDVI (6S+BRDF)',
                             'MOD09GA vs 6S+BRDF', 'blue')

    if 'NDVI_MOD09GA' in df.columns and 'NDVI_soz' in df.columns:
        plot_density_scatter(axes[0, 1], df['NDVI_MOD09GA'], df['NDVI_soz'],
                             'MODIS MOD09GA NDVI', 'Himawari-8 NDVI (Solar Angle adjusted)',
                             'MOD09GA vs Solar Angle', 'green')

    # 第二排: MOD13A1比较
    if 'NDVI_MOD13A1' in df.columns and 'NDVI_6s' in df.columns:
        plot_density_scatter(axes[1, 0], df['NDVI_MOD13A1'], df['NDVI_6s'],
                             'MODIS MOD13A1 NDVI', 'Himawari-8 NDVI (6S+BRDF)',
                             'MOD13A1 vs 6S+BRDF', 'blue')

    if 'NDVI_MOD13A1' in df.columns and 'NDVI_soz' in df.columns:
        plot_density_scatter(axes[1, 1], df['NDVI_MOD13A1'], df['NDVI_soz'],
                             'MODIS MOD13A1 NDVI', 'Himawari-8 NDVI (Solar Angle adjusted)',
                             'MOD13A1 vs Solar Angle', 'green')

    # 第三排: MOD43A4比较 (新增)
    if 'NDVI_MOD43A4' in df.columns and 'NDVI_6s' in df.columns:
        plot_density_scatter(axes[2, 0], df['NDVI_MOD43A4'], df['NDVI_6s'],
                             'MODIS MOD43A4 NDVI (Nadir)', 'Himawari-8 NDVI (6S+BRDF)',
                             'MOD43A4 Nadir vs 6S+BRDF', 'purple')

    if 'NDVI_MOD43A4' in df.columns and 'NDVI_soz' in df.columns:
        plot_density_scatter(axes[2, 1], df['NDVI_MOD43A4'], df['NDVI_soz'],
                             'MODIS MOD43A4 NDVI (Nadir)', 'Himawari-8 NDVI (Solar Angle adjusted)',
                             'MOD43A4 Nadir vs Solar Angle', 'orange')

    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, 'NDVI_CrossValidation_ScatterDensity.png'), dpi=300)
    plt.close()

    # 2. 误差分布图
    plt.figure(figsize=(14, 15))

    plt.subplot(3, 1, 1)
    if 'NDVI_MOD09GA' in df.columns and 'NDVI_6s' in df.columns:
        df['error_6s_mod09'] = df['NDVI_6s'] - df['NDVI_MOD09GA']
        sns.kdeplot(data=df, x='error_6s_mod09', label='6S+BRDF vs MOD09GA', fill=True, alpha=0.5)

    if 'NDVI_MOD09GA' in df.columns and 'NDVI_soz' in df.columns:
        df['error_soz_mod09'] = df['NDVI_soz'] - df['NDVI_MOD09GA']
        sns.kdeplot(data=df, x='error_soz_mod09', label='Solar Angle vs MOD09GA', fill=True, alpha=0.5)

    plt.axvline(x=0, color='gray', linestyle='--')
    plt.xlabel('NDVI Difference (Himawari-8 - MODIS)')
    plt.ylabel('Density')
    plt.title('Error distribution: MOD09GA')
    plt.legend()
    plt.grid(True, alpha=0.3)

    plt.subplot(3, 1, 2)
    if 'NDVI_MOD13A1' in df.columns and 'NDVI_6s' in df.columns:
        df['error_6s_mod13'] = df['NDVI_6s'] - df['NDVI_MOD13A1']
        sns.kdeplot(data=df, x='error_6s_mod13', label='6S+BRDF vs MOD13A1', fill=True, alpha=0.5)

    if 'NDVI_MOD13A1' in df.columns and 'NDVI_soz' in df.columns:
        df['error_soz_mod13'] = df['NDVI_soz'] - df['NDVI_MOD13A1']
        sns.kdeplot(data=df, x='error_soz_mod13', label='Solar Angle vs MOD13A1', fill=True, alpha=0.5)

    plt.axvline(x=0, color='gray', linestyle='--')
    plt.xlabel('NDVI Difference (Himawari-8 - MODIS)')
    plt.ylabel('Density')
    plt.title('Error distribution: MOD13A1')
    plt.legend()
    plt.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, 'NDVI_Error_Distribution.png'), dpi=300)
    plt.close()

    plt.subplot(3, 1, 3)  # 新增第3个子图
    if 'NDVI_MOD43A4' in df.columns and 'NDVI_6s' in df.columns:
        df['error_6s_mod43'] = df['NDVI_6s'] - df['NDVI_MOD43A4']
        sns.kdeplot(data=df, x='error_6s_mod43', label='6S+BRDF vs MOD43A4 Nadir', fill=True, alpha=0.5, color='purple')

    if 'NDVI_MOD43A4' in df.columns and 'NDVI_soz' in df.columns:
        df['error_soz_mod43'] = df['NDVI_soz'] - df['NDVI_MOD43A4']
        sns.kdeplot(data=df, x='error_soz_mod43', label='Solar Angle vs MOD43A4 Nadir', fill=True, alpha=0.5,
                    color='orange')

    plt.axvline(x=0, color='gray', linestyle='--')
    plt.xlabel('NDVI Difference (Himawari-8 - MODIS)')
    plt.ylabel('Density')
    plt.title('Error distribution: MOD43A4 Nadir')
    plt.legend()
    plt.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, 'NDVI_Error_Distribution.png'), dpi=300)
    plt.close()

    # 3. 统计指标表
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

    # 初始化指标字典
    metrics_data = []

    # MOD09GA比较
    if 'NDVI_MOD09GA' in df.columns and 'NDVI_6s' in df.columns:
        metrics_mod09_6s = calculate_metrics(df['NDVI_MOD09GA'], df['NDVI_6s'])
        metrics_data.append({
            'Comparison': 'MOD09GA vs 6S+BRDF',
            'R²': metrics_mod09_6s['r2'],
            'RMSE': metrics_mod09_6s['rmse'],
            'Bias': metrics_mod09_6s['bias'],
            'Slope': metrics_mod09_6s['slope'],
            'n': metrics_mod09_6s['count']
        })

    if 'NDVI_MOD09GA' in df.columns and 'NDVI_soz' in df.columns:
        metrics_mod09_soz = calculate_metrics(df['NDVI_MOD09GA'], df['NDVI_soz'])
        metrics_data.append({
            'Comparison': 'MOD09GA vs Solar Angle',
            'R²': metrics_mod09_soz['r2'],
            'RMSE': metrics_mod09_soz['rmse'],
            'Bias': metrics_mod09_soz['bias'],
            'Slope': metrics_mod09_soz['slope'],
            'n': metrics_mod09_soz['count']
        })

    # MOD13A1比较
    if 'NDVI_MOD13A1' in df.columns and 'NDVI_6s' in df.columns:
        metrics_mod13_6s = calculate_metrics(df['NDVI_MOD13A1'], df['NDVI_6s'])
        metrics_data.append({
            'Comparison': 'MOD13A1 vs 6S+BRDF',
            'R²': metrics_mod13_6s['r2'],
            'RMSE': metrics_mod13_6s['rmse'],
            'Bias': metrics_mod13_6s['bias'],
            'Slope': metrics_mod13_6s['slope'],
            'n': metrics_mod13_6s['count']
        })

    if 'NDVI_MOD13A1' in df.columns and 'NDVI_soz' in df.columns:
        metrics_mod13_soz = calculate_metrics(df['NDVI_MOD13A1'], df['NDVI_soz'])
        metrics_data.append({
            'Comparison': 'MOD13A1 vs Solar Angle',
            'R²': metrics_mod13_soz['r2'],
            'RMSE': metrics_mod13_soz['rmse'],
            'Bias': metrics_mod13_soz['bias'],
            'Slope': metrics_mod13_soz['slope'],
            'n': metrics_mod13_soz['count']
        })

        # MOD43A4比较
        if 'NDVI_MOD43A4' in df.columns and 'NDVI_6s' in df.columns:
            metrics_mod43_6s = calculate_metrics(df['NDVI_MOD43A4'], df['NDVI_6s'])
            metrics_data.append({
                'Comparison': 'MOD43A4 Nadir vs 6S+BRDF',
                'R²': metrics_mod43_6s['r2'],
                'RMSE': metrics_mod43_6s['rmse'],
                'Bias': metrics_mod43_6s['bias'],
                'Slope': metrics_mod43_6s['slope'],
                'n': metrics_mod43_6s['count']
            })

        if 'NDVI_MOD43A4' in df.columns and 'NDVI_soz' in df.columns:
            metrics_mod43_soz = calculate_metrics(df['NDVI_MOD43A4'], df['NDVI_soz'])
            metrics_data.append({
                'Comparison': 'MOD43A4 Nadir vs Solar Angle',
                'R²': metrics_mod43_soz['r2'],
                'RMSE': metrics_mod43_soz['rmse'],
                'Bias': metrics_mod43_soz['bias'],
                'Slope': metrics_mod43_soz['slope'],
                'n': metrics_mod43_soz['count']
            })

    if not metrics_data:
        print("没有足够的指标数据生成统计表")
        return

    stats_table = pd.DataFrame(metrics_data)
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
            all_data.append(df)

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
def main():
    """主程序"""
    parser = argparse.ArgumentParser(description='NDVI交叉验证分析')
    parser.add_argument('--stage1', action='store_true', help='运行阶段1：重组站点时间序列数据')
    parser.add_argument('--stage2', action='store_true', help='运行阶段2：交叉验证分析')

    args = parser.parse_args()

    if args.stage1:
        run_stage1()
    if args.stage2:
        run_stage2()

    if not args.stage1 and not args.stage2:
        print("请指定要运行的阶段：--stage1 或 --stage2")


if __name__ == "__main__":
    main()