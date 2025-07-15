import os
import netCDF4 as nc
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# 配置参数
DATE = '20150708'  # 格式: YYYYMMDD
STATION_NAME = '3562A'  # 替换为实际站点名称
MODIS_DIR = 'D:/H8_Data/MODIS_NDVI'  # MODIS数据目录
TOA_DIR = 'D:/H8_data/Hourly_TOA_Angles'  # TOA数据目录（修改点）
OUTPUT_DIR = 'D:/H8_Data/NDVI_cross_validation/output_plots'  # 输出目录

def read_modis_data(date, station_name):
    """读取MODIS单日数据文件（保持不变）"""
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

        # 获取NDVI值
        terra_ndvi = ds.variables['NDVI_Terra'][idx]
        aqua_ndvi = ds.variables['NDVI_Aqua'][idx]

        # 处理缺失值
        if terra_ndvi == -9999.0 or np.isnan(terra_ndvi):
            terra_ndvi = np.nan
        if aqua_ndvi == -9999.0 or np.isnan(aqua_ndvi):
            aqua_ndvi = np.nan

        # 创建北京时间 (UTC+8)
        date_obj = datetime.strptime(date, '%Y%m%d')
        terra_time = datetime(date_obj.year, date_obj.month, date_obj.day, 10, 0)  # 北京时间10:00
        aqua_time = datetime(date_obj.year, date_obj.month, date_obj.day, 13, 0)  # 北京时间13:00

        return terra_time, terra_ndvi, aqua_time, aqua_ndvi

    except FileNotFoundError:
        print(f"错误: MODIS文件未找到: {file_path}")
        return None, None, None, None
    except Exception as e:
        print(f"读取MODIS数据时出错: {e}")
        return None, None, None, None

def read_toa_data(date, station_name):
    """读取TOA数据并计算NDVI（修改点）"""
    toa_times = []
    toa_ndvi = []
    year = date[:4]
    month = date[4:6]

    # UTC时间范围: 00:00-12:00 (对应北京时间08:00-20:00)
    for utc_hour in range(0, 13):  # 0到12小时
        hh = str(utc_hour).zfill(2)
        file_path = os.path.join(TOA_DIR, year, month, f'H8_hourly_TOA_angles_{date}_{hh}00.nc')

        if not os.path.exists(file_path):
            print(f"TOA文件未找到: {file_path}")
            continue

        try:
            ds = nc.Dataset(file_path)
            stations = ds.variables['Station'][:]
            station_names = [''.join(s).strip() for s in stations]

            if station_name not in station_names:
                print(f"警告: 站点 '{station_name}' 未在TOA文件 {file_path} 中找到")
                continue

            idx = station_names.index(station_name)

            # 检查数据可用性
            avail = ds.variables['hourly_availability'][idx]
            if avail != 0:
                print(f"数据不可用: {station_name} @ {date}_{hh}00")
                continue

            # 获取波段反射率
            band3 = ds.variables['Albedo_03'][idx]  # 红波段
            band4 = ds.variables['Albedo_04'][idx]  # 近红外波段

            # 计算NDVI
            denominator = band4 + band3
            if denominator > 0.01:  # 避免除以零
                ndvi_val = (band4 - band3) / denominator
            else:
                ndvi_val = np.nan

            # 检查NDVI有效性
            if np.isnan(ndvi_val) or ndvi_val < -1.0 or ndvi_val > 1.0:
                print(f"无效NDVI值: {ndvi_val} @ {date}_{hh}00")
                continue

            # 转换为北京时间 (UTC+8)
            utc_time = datetime.strptime(f"{date}{hh}", '%Y%m%d%H')
            bj_time = utc_time + timedelta(hours=8)

            toa_times.append(bj_time)
            toa_ndvi.append(ndvi_val)

        except Exception as e:
            print(f"读取TOA文件 {file_path} 时出错: {e}")

    return toa_times, toa_ndvi

def plot_ndvi_data(date, station_name):
    """绘制NDVI时间序列图（修改图例标签）"""
    # 读取数据
    terra_time, terra_ndvi, aqua_time, aqua_ndvi = read_modis_data(date, station_name)
    toa_times, toa_ndvi = read_toa_data(date, station_name)  # 修改点

    # 检查是否有有效数据
    all_data = [toa_ndvi]  # 修改点
    if terra_ndvi is not None and not np.isnan(terra_ndvi):
        all_data.append([terra_ndvi])
    if aqua_ndvi is not None and not np.isnan(aqua_ndvi):
        all_data.append([aqua_ndvi])

    if all(not data for data in all_data):
        print(f"错误: 没有找到 {station_name} 在 {date} 的有效NDVI数据")
        return

    # 创建图形
    plt.figure(figsize=(12, 6))

    # 绘制TOA计算的NDVI数据（修改点）
    if toa_ndvi:
        plt.plot(toa_times, toa_ndvi, 'g-', linewidth=1.5, marker='o', markersize=4,
                 label='Himawari-8 TOA NDVI')  # 修改图例标签

    # 绘制MODIS Terra数据
    if terra_ndvi is not None and not np.isnan(terra_ndvi):
        plt.plot(terra_time, terra_ndvi, 'bo', markersize=8, label='Terra MODIS')

    # 绘制MODIS Aqua数据
    if aqua_ndvi is not None and not np.isnan(aqua_ndvi):
        plt.plot(aqua_time, aqua_ndvi, 'ro', markersize=8, label='Aqua MODIS')

    # 设置图形属性
    plt.title(f'TOA NDVI vs MODIS NDVI at {station_name}\nDate: {date}', fontsize=14)  # 修改标题
    plt.xlabel('Beijing Time (UTC+8)', fontsize=12)
    plt.ylabel('NDVI', fontsize=12)
    plt.grid(True, linestyle='--', alpha=0.7)
    plt.ylim(-0.2, 1.0)  # NDVI典型范围

    # 设置x轴时间格式
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    plt.gca().xaxis.set_major_locator(mdates.HourLocator(interval=2))
    plt.gcf().autofmt_xdate()

    # 添加图例
    plt.legend(loc='best')

    # 保存和显示图形
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(OUTPUT_DIR, f'TOA_MODIS_NDVI_{station_name}_{date}.png')  # 修改文件名
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    print(f"图形已保存至: {output_path}")
    plt.show()

# 执行绘图
plot_ndvi_data(DATE, STATION_NAME)