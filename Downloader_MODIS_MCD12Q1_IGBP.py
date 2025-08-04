import ee
import datetime
import os
import math
import logging
import time
import numpy as np
import netCDF4 as nc
import xarray as xr
from collections import defaultdict
import traceback

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler()]
)


# GEE授权
def GEE_authorizing():
    service_account = "lobstyu@premium-cipher-424203-d0.iam.gserviceaccount.com"
    credentials_path = 'premium-cipher-424203-d0-c6894a29d00c.json'
    try:
        credentials = ee.ServiceAccountCredentials(service_account, credentials_path)
        ee.Initialize(credentials)
        logging.info("GEE 初始化成功")
    except Exception as e:
        logging.error(f"GEE 初始化失败: {e}")
        raise


# 读取LUTs.nc文件获取站点信息
def read_luts_nc(luts_path):
    try:
        ds = xr.open_dataset(luts_path)
        logging.info(f"成功读取 LUTs.nc 文件")

        stations = ds['Station'].values
        lats = ds['Lat'].values
        lons = ds['Lon'].values

        return stations, lats, lons
    except Exception as e:
        logging.error(f"读取 LUTs.nc 文件失败: {e}")
        raise


# 计算Himawari网格
def get_himawari_grid(lon, lat):
    x_index = math.floor((lon - 80) / 0.05)
    y_index = math.floor((60 - lat) / 0.05)
    west = 80 + x_index * 0.05
    east = west + 0.05
    north = 60 - y_index * 0.05
    south = north - 0.05
    return west, south, east, north, x_index, y_index


# 创建Himawari网格的FeatureCollection
def get_feature_collection(stations, lats, lons):
    try:
        features = []
        grid_info = []
        station_to_grid = {}

        for i, (station, lat, lon) in enumerate(zip(stations, lats, lons)):
            west, south, east, north, x_index, y_index = get_himawari_grid(lon, lat)
            grid_key = (x_index, y_index)

            # 如果网格已存在，添加到现有网格
            if grid_key in station_to_grid:
                station_to_grid[grid_key].append(i)
            else:
                station_to_grid[grid_key] = [i]
                rect = ee.Geometry.Rectangle([west, south, east, north])
                feature = ee.Feature(
                    rect,
                    {
                        'grid_x': x_index,
                        'grid_y': y_index,
                        'grid_key': f"{x_index}_{y_index}"
                    }
                )
                features.append(feature)
                grid_info.append((x_index, y_index))

        fc = ee.FeatureCollection(features)
        logging.info(f"成功创建Himawari网格FeatureCollection，包含 {len(features)} 个网格")
        return fc, grid_info, station_to_grid
    except Exception as e:
        logging.error(f"创建FeatureCollection失败: {e}")
        raise


# 处理年度土地覆盖数据
def process_annual_lc(year, grid_fc, station_to_grid, stations, max_retries=5):
    """
    处理单个年份的土地覆盖数据

    参数:
    year: 年份 (int)
    grid_fc: Himawari网格FeatureCollection
    station_to_grid: 站点到网格的映射字典
    stations: 站点名称列表
    max_retries: 最大重试次数

    返回:
    station_data: 每个站点的土地覆盖值数组
    year: 处理的年份
    """
    retry_count = 0
    while retry_count < max_retries:
        try:
            # 设置日期范围
            start_date = f"{year}-01-01"
            end_date = f"{year + 1}-01-01"

            # 获取年度土地覆盖数据
            collection = ee.ImageCollection("MODIS/061/MCD12Q1").select(['LC_Type1'])
            image = collection.filterDate(start_date, end_date).first()

            if not image:
                logging.warning(f"{year}年土地覆盖数据未找到")
                return None, None

            # 使用众数统计进行重采样
            reduced = image.reduceRegions(
                collection=grid_fc,
                reducer=ee.Reducer.mode(),
                scale=500  # MODIS原始分辨率
            )

            # 获取结果
            result_info = reduced.getInfo()

            # 处理结果数据
            grid_data = {}
            if 'features' in result_info:
                for f in result_info['features']:
                    props = f['properties']
                    grid_x = props['grid_x']
                    grid_y = props['grid_y']
                    grid_key = (grid_x, grid_y)

                    # 获取众数值（可能为列表，取第一个值）
                    mode_value = props.get('mode', -9999)
                    if isinstance(mode_value, list) and len(mode_value) > 0:
                        grid_data[grid_key] = int(mode_value[0])
                    else:
                        grid_data[grid_key] = int(mode_value) if mode_value != -9999 else -9999

            # 将网格数据映射到站点
            station_data = np.full(len(stations), -9999, dtype=np.int16)
            for grid_key, lc_value in grid_data.items():
                station_indices = station_to_grid.get(grid_key, [])
                for idx in station_indices:
                    station_data[idx] = lc_value

            logging.info(f"成功处理 {year} 年土地覆盖数据")
            return station_data, year

        except Exception as e:
            retry_count += 1
            error_type = type(e).__name__
            logging.warning(f"处理 {year} 年数据时出错 ({error_type}): {e}，重试 {retry_count}/{max_retries}")
            time.sleep(5 * retry_count)  # 指数退避等待

            if retry_count >= max_retries:
                logging.error(f"处理 {year} 年数据失败，已达到最大重试次数")
                traceback.print_exc()
                return None, None


# 主函数
def main():
    # 初始化GEE
    GEE_authorizing()

    # 数据路径
    data_path = r"D:/H8_data"
    luts_path = os.path.join(data_path, "LUTs.nc")
    output_path = os.path.join(data_path, "LC_resampled_2015_2024.nc")

    # 读取LUTs.nc文件
    stations, lats, lons = read_luts_nc(luts_path)
    logging.info(f"共读取 {len(stations)} 个站点")

    # 创建Himawari网格FeatureCollection
    grid_fc, grid_info, station_to_grid = get_feature_collection(stations, lats, lons)

    # 设置年份范围
    years = list(range(2015, 2025))

    # 存储所有年份的土地覆盖数据
    all_station_data = []
    valid_years = []

    # 处理每年的土地覆盖数据
    for year in years:
        station_data, processed_year = process_annual_lc(year, grid_fc, station_to_grid, stations)
        if station_data is not None:
            all_station_data.append(station_data)
            valid_years.append(processed_year)

    if not all_station_data:
        logging.error("未成功处理任何年份的数据，程序终止")
        return

    # 转换为numpy数组
    lc_array = np.array(all_station_data, dtype=np.int16)

    # 创建时间变量（以2015-01-01为基准）
    time_values = np.array([year - 2015 for year in valid_years], dtype=np.int32)

    # 创建输出NetCDF文件
    try:
        with nc.Dataset(output_path, 'w', format='NETCDF4') as ds:
            # 添加全局属性
            ds.title = "Resampled MODIS MCD12Q1 Land Cover Classification (IGBP)"
            ds.history = f"Created on {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            ds.source = "Google Earth Engine: MODIS/061/MCD12Q1"
            ds.Conventions = "CF-1.8"

            # 创建维度
            ds.createDimension('Station', len(stations))
            ds.createDimension('time', len(valid_years))

            # 创建变量
            # 站点名称 - 使用固定长度字符串类型
            station_var = ds.createVariable('Station', 'S10', ('Station',))
            station_var.long_name = "Station identifier"

            # 纬度
            lat_var = ds.createVariable('Lat', 'f4', ('Station',))
            lat_var.units = "degrees_north"
            lat_var.long_name = "Latitude"

            # 经度
            lon_var = ds.createVariable('Lon', 'f4', ('Station',))
            lon_var.units = "degrees_east"
            lon_var.long_name = "Longitude"

            # 时间
            time_var = ds.createVariable('time', 'i4', ('time',))
            time_var.units = "years since 2015-01-01"
            time_var.calendar = "standard"
            time_var.long_name = "Time"

            # 土地覆盖 - 修复：在创建变量时设置fill_value
            fill_value = np.int16(-9999)
            lc_var = ds.createVariable(
                'LC_type1',
                'i2',
                ('time', 'Station'),
                fill_value=fill_value
            )
            lc_var.long_name = "IGBP Land Cover Type 1 Classification"
            lc_var.units = "class"
            lc_var.missing_value = fill_value  # 单独设置missing_value属性

            # 写入数据
            # 转换站点名称为固定长度字符串
            station_names = np.array([s.ljust(10)[:10] for s in stations], dtype='S10')
            station_var[:] = station_names

            lat_var[:] = lats
            lon_var[:] = lons
            time_var[:] = time_values
            lc_var[:] = lc_array

        logging.info(f"成功创建土地覆盖文件: {output_path}")
        logging.info(f"文件大小: {os.path.getsize(output_path) / 1024 / 1024:.2f} MB")

    except Exception as e:
        logging.error(f"创建输出文件失败: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    main()