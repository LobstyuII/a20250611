import os
import netCDF4 as nc
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
from datetime import datetime, timedelta

# 配置参数
DATE = '20150709'  # 格式: YYYYMMDD
STATION_NAME = '2652A'
SOZSR_DIR = 'D:/H8_data/Hourly_sozSR_Angles'  # sozSR反射率数据目录
H8SR_DIR = 'D:/H8_data/H8SR'  # H8SR反射率数据目录
MODIS_DIR = 'D:/H8_Data/MODIS_NDVI'  # MODIS数据目录
OUTPUT_DIR = 'D:/H8_Data/NDVI_cross_validation/output_plots'  # 输出目录
DEPRECATED_STATIONS_FILE = 'D:/H8_data/Station_deprecated.nc'  # 废弃站点列表文件


def get_deprecated_stations():
    """获取废弃站点列表"""
    try:
        ds = nc.Dataset(DEPRECATED_STATIONS_FILE)
        stations = ds.variables['Station'][:]
        return [''.join(s).strip() for s in stations]
    except Exception as e:
        print(f"读取废弃站点文件时出错: {e}")
        return []


def read_modis_data(date, station_name):
    """读取MODIS单日数据文件"""
    deprecated = get_deprecated_stations()
    if station_name in deprecated:
        print(f"警告: 站点 '{station_name}' 已被废弃")
        return None, None, None, None

    year = date[:4]
    month = date[4:6]
    file_path = os.path.join(MODIS_DIR, year, month, f'MODIS_NDVI_{date}.nc')
    try:
        ds = nc.Dataset(file_path)
        stations = ds.variables['Station'][:]
        station_names = [''.join(s).strip() for s in stations]
        if station_name not in station_names:
            print(f"警告: 站点 '{station_name}' 未在MODIS数据中找到")
            return None, None, None, None

        idx = station_names.index(station_name)
        terra_ndvi = ds.variables['NDVI_Terra'][idx]
        aqua_ndvi = ds.variables['NDVI_Aqua'][idx]
        # 处理缺失值
        if terra_ndvi == -9999.0 or np.isnan(terra_ndvi):
            terra_ndvi = np.nan
        if aqua_ndvi == -9999.0 or np.isnan(aqua_ndvi):
            aqua_ndvi = np.nan

        date_obj = datetime.strptime(date, '%Y%m%d')
        terra_time = datetime(date_obj.year, date_obj.month, date_obj.day, 10, 0)
        aqua_time = datetime(date_obj.year, date_obj.month, date_obj.day, 13, 0)
        return terra_time, terra_ndvi, aqua_time, aqua_ndvi
    except FileNotFoundError:
        print(f"错误: MODIS文件未找到: {file_path}")
        return None, None, None, None
    except Exception as e:
        print(f"读取MODIS数据时出错: {e}")
        return None, None, None, None


def read_sozSR_data(date, station_name):
    """读取sozSR数据并计算NDVI"""
    deprecated = get_deprecated_stations()
    if station_name in deprecated:
        print(f"警告: 站点 '{station_name}' 已被废弃")
        return [], []

    times, ndvi_vals = [], []
    date_dt = datetime.strptime(date, '%Y%m%d')
    prev_date = (date_dt - timedelta(days=1)).strftime('%Y%m%d')
    ranges = [(prev_date, [21,22,23]), (date, list(range(0,12)))]

    for date_str, hours in ranges:
        for hh in hours:
            hour_str = str(hh).zfill(2)
            file_path = os.path.join(SOZSR_DIR, date_str[:4], date_str[4:6],
                                     f'H8_hourly_sozSR_angles_{date_str}_{hour_str}00.nc')
            if not os.path.exists(file_path):
                continue
            try:
                ds = nc.Dataset(file_path)
                stations = ds.variables['Station'][:]
                names = [''.join(s).strip() for s in stations]
                if station_name not in names:
                    continue
                idx = names.index(station_name)
                avail = ds.variables['hourly_availability'][idx]
                if avail != 0:
                    continue
                b3 = ds.variables['Albedo_03'][idx]
                b4 = ds.variables['Albedo_04'][idx]
                denom = b4 + b3
                ndv = (b4 - b3) / denom if denom > 0.01 else np.nan
                if np.isnan(ndv) or ndv < -1 or ndv > 1:
                    continue
                utc = datetime.strptime(f"{date_str}{hour_str}", '%Y%m%d%H')
                bj = utc + timedelta(hours=8)
                times.append(bj)
                ndvi_vals.append(ndv)
            except Exception as e:
                print(f"读取sozSR文件 {file_path} 时出错: {e}")
    order = np.argsort(times)
    return [times[i] for i in order], [ndvi_vals[i] for i in order]


def read_h8sr_data(date, station_name):
    """读取H8SR数据并计算NDVI"""
    deprecated = get_deprecated_stations()
    if station_name in deprecated:
        print(f"警告: 站点 '{station_name}' 已被废弃")
        return [], []

    times, ndvi_vals = [], []
    date_dt = datetime.strptime(date, '%Y%m%d')
    prev_date = (date_dt - timedelta(days=1)).strftime('%Y%m%d')
    ranges = [(prev_date, [21,22,23]), (date, list(range(0,12)))]

    for date_str, hours in ranges:
        for hh in hours:
            hour_str = str(hh).zfill(2)
            file_path = os.path.join(H8SR_DIR, f'6SSR_{date_str}_{hour_str}00.nc')
            if not os.path.exists(file_path):
                continue
            try:
                ds = nc.Dataset(file_path)
                stations = ds.variables['Station'][:]
                names = [''.join(s).strip() for s in stations]
                if station_name not in names:
                    continue
                idx = names.index(station_name)
                # avail = ds.variables['hourly_availability'][idx]
                # if avail != 0:
                #     continue
                b3 = ds.variables['Albedo_03'][idx]
                b4 = ds.variables['Albedo_04'][idx]
                denom = b4 + b3
                ndv = (b4 - b3) / denom if denom > 0.01 else np.nan
                if np.isnan(ndv) or ndv < -1 or ndv > 1:
                    continue
                utc = datetime.strptime(f"{date_str}{hour_str}", '%Y%m%d%H')
                bj = utc + timedelta(hours=8)
                times.append(bj)
                ndvi_vals.append(ndv)
            except Exception as e:
                print(f"读取H8SR文件 {file_path} 时出错: {e}")
    order = np.argsort(times)
    return [times[i] for i in order], [ndvi_vals[i] for i in order]


def plot_ndvi_comparison(date, station_name):
    """绘制三种NDVI数据对比图: sozSR, H8SR, MODIS"""
    terra_time, terra_ndvi, aqua_time, aqua_ndvi = read_modis_data(date, station_name)
    soz_times, soz_ndvi = read_sozSR_data(date, station_name)
    sr_times, sr_ndvi = read_h8sr_data(date, station_name)

    has_data = False
    sources = []
    if soz_ndvi:
        has_data = True; sources.append('sozSR')
    if sr_ndvi:
        has_data = True; sources.append('H8SR')
    if (terra_ndvi is not None and not np.isnan(terra_ndvi)) or \
       (aqua_ndvi is not None and not np.isnan(aqua_ndvi)):
        has_data = True; sources.append('MODIS')
    if not has_data:
        print(f"错误: 没有找到 {station_name} 在 {date} 的有效NDVI数据")
        return

    fig, ax = plt.subplots(figsize=(14, 8))
    if soz_ndvi:
        ax.plot(soz_times, soz_ndvi, 'b-', label='Himawari-8 sozSR NDVI', marker='o')
    if sr_ndvi:
        ax.plot(sr_times, sr_ndvi, 'c-', label='Himawari-8 SR NDVI', marker='d')
    if terra_ndvi is not None and not np.isnan(terra_ndvi):
        ax.plot(terra_time, terra_ndvi, 'gD', label='Terra MODIS')
    if aqua_ndvi is not None and not np.isnan(aqua_ndvi):
        ax.plot(aqua_time, aqua_ndvi, 'mD', label='Aqua MODIS')

    plt.title(f'NDVI Comparison at {station_name}\nDate: {date}', fontsize=16)
    plt.xlabel('Beijing Time (UTC+8)', fontsize=14)
    plt.ylabel('NDVI', fontsize=14)
    plt.grid(True, linestyle='--', alpha=0.7)
    plt.ylim(-0.2, 1.0)

    date_obj = datetime.strptime(date, '%Y%m%d')
    ax.set_xlim(date_obj.replace(hour=5), date_obj.replace(hour=21))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=2))
    fig.autofmt_xdate()

    ax.legend(loc='best', fontsize=12)

    info = []
    if soz_ndvi: info.append(f'sozSR Points: {len(soz_ndvi)}')
    if sr_ndvi:  info.append(f'H8SR Points: {len(sr_ndvi)}')
    if info:
        ax.annotate("\n".join(info), xy=(0.02, 0.95), xycoords='axes fraction',
                    fontsize=11, bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="gray", alpha=0.8))

    # 统计信息
    stats = []
    # sozSR vs H8SR
    common = set(soz_times) & set(sr_times)
    if common:
        vals1 = [v for t, v in zip(soz_times, soz_ndvi) if t in common]
        vals2 = [v for t, v in zip(sr_times, sr_ndvi) if t in common]
        diff = np.array(vals1) - np.array(vals2)
        stats.append(f'sozSR vs H8SR (n={len(common)}):')
        stats.append(f'Mean diff: {np.mean(diff):.4f}')
        stats.append(f'RMSE: {np.sqrt(np.mean(diff**2)):.4f}')
    # MODIS mean
    mvals = []
    if terra_ndvi is not None and not np.isnan(terra_ndvi): mvals.append(terra_ndvi)
    if aqua_ndvi is not None and not np.isnan(aqua_ndvi): mvals.append(aqua_ndvi)
    if mvals:
        stats.append(f'MODIS Mean: {np.mean(mvals):.4f}')
    if stats:
        ax.annotate("\n".join(stats), xy=(0.75, 0.95), xycoords='axes fraction',
                    fontsize=11, bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="gray", alpha=0.8))

    plt.figtext(0.5, 0.01, f"Data sources: {', '.join(sources)}",
                ha="center", fontsize=10, bbox={"facecolor": "white", "alpha": 0.7, "pad": 5})

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out = os.path.join(OUTPUT_DIR, f'NDVI_Comparison_{station_name}_{date}.png')
    plt.savefig(out, dpi=300, bbox_inches='tight')
    print(f"图形已保存至: {out}")
    plt.show()

if __name__ == "__main__":
    plot_ndvi_comparison(DATE, STATION_NAME)
