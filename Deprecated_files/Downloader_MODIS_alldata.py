import ee
import datetime
import os
import math
import logging
import time
import numpy as np
import netCDF4 as nc
import xarray as xr
from tqdm import tqdm
import concurrent.futures
import traceback
import shutil
from collections import defaultdict

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler()]
)


# GEE授权
def GEE_authorizing():
    service_account = "lobstyu@premium-cipher-424203-d0.iam.gserviceaccount.com"
    credentials_path = '../premium-cipher-424203-d0-c6894a29d00c.json'
    try:
        credentials = ee.ServiceAccountCredentials(service_account, credentials_path)
        ee.Initialize(credentials)
        logging.info("GEE 初始化成功")
    except Exception as e:
        logging.error(f"GEE 初始化失败: {e}")
        raise


# 读取LUTs.nc文件
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


# 保存原始像元数据到临时文件
def save_raw_data(date, grid_data, stations, lats, lons, grid_info, station_to_grid, base_path, product):
    try:
        # 创建目录
        year = date.strftime("%Y")
        month = date.strftime("%m")
        dir_path = os.path.join(base_path, f"MODIS_RAW_{product}", year, month)
        os.makedirs(dir_path, exist_ok=True)

        # 文件路径
        filename = f"MODIS_RAW_{product}_{date.strftime('%Y%m%d')}.nc"
        file_path = os.path.join(dir_path, filename)

        # 如果文件已存在且完整，则跳过
        if os.path.exists(file_path) and os.path.getsize(file_path) > 1024:
            logging.info(f"文件已存在: {file_path}")
            return True

        # 创建新的NC文件
        with nc.Dataset(file_path, 'w', format='NETCDF4') as ds:
            # 定义维度
            ds.createDimension('grid', len(grid_info))
            ds.createDimension('station', len(stations))

            # 定义变量
            gridx_var = ds.createVariable('grid_x', 'i4', ('grid',))
            gridy_var = ds.createVariable('grid_y', 'i4', ('grid',))

            station_var = ds.createVariable('station_index', 'i4', ('station',))
            station_name_var = ds.createVariable('station_name', str, ('station',))
            lat_var = ds.createVariable('lat', 'f4', ('station',))
            lon_var = ds.createVariable('lon', 'f4', ('station',))

            # 添加日期作为全局属性
            ds.date = date.strftime("%Y-%m-%d")
            ds.product = product

            # 写入网格数据
            gridx = [g[0] for g in grid_info]
            gridy = [g[1] for g in grid_info]
            gridx_var[:] = gridx
            gridy_var[:] = gridy

            # 写入站点数据
            station_var[:] = np.arange(len(stations))
            station_name_var[:] = np.array(stations, dtype=object)
            lat_var[:] = lats
            lon_var[:] = lons

            # 根据产品类型保存数据
            if product == "MCD43A1":
                # 创建BRDF参数变量
                for band in [1, 2]:
                    for param in ['iso', 'vol', 'geo']:
                        varname = f'Band{band}_{param}'
                        var = ds.createVariable(varname, 'f4', ('grid',), fill_value=-9999.0)
                        var[:] = [grid_data.get((gx, gy), {}).get(varname, -9999.0) for (gx, gy) in grid_info]

            elif product == "MCD43A4":
                # 创建反射率变量
                for band in [1, 2]:
                    varname = f'Nadir_Reflectance_Band{band}'
                    var = ds.createVariable(varname, 'f4', ('grid',), fill_value=-9999.0)
                    var[:] = [grid_data.get((gx, gy), {}).get(varname, -9999.0) for (gx, gy) in grid_info]

            elif product == "MCD12Q1":
                # 创建土地覆盖变量
                lc_var = ds.createVariable('LC_Type1', 'i2', ('grid',), fill_value=-9999)
                lc_var[:] = [grid_data.get((gx, gy), {}).get('LC_Type1', -9999) for (gx, gy) in grid_info]

            # 保存网格到站点的映射关系
            mapping = np.full((len(grid_info), len(stations)), -1, dtype=np.int32)
            for grid_idx, (gx, gy) in enumerate(grid_info):
                station_indices = station_to_grid.get((gx, gy), [])
                for i, station_idx in enumerate(station_indices):
                    if i < mapping.shape[1]:
                        mapping[grid_idx, i] = station_idx

            mapping_var = ds.createVariable('grid_station_mapping', 'i4', ('grid', 'station'))
            mapping_var[:] = mapping

        logging.info(f"成功保存: {file_path}")
        return True
    except Exception as e:
        logging.error(f"保存 {date} {product} 原始数据失败: {e}")
        traceback.print_exc()
        return False


# 处理每日原始数据
def process_daily_raw_data(date, collection, grid_fc, stations, lats, lons, grid_info, station_to_grid, base_path,
                           product, max_retries=5):
    retry_count = 0
    while retry_count < max_retries:
        try:
            # 设置日期范围
            start_date = datetime.datetime(date.year, date.month, date.day, 0, 0, 0)
            end_date = start_date + datetime.timedelta(days=1)

            # 获取当天的数据
            img = collection.filterDate(start_date, end_date).first()

            # 初始化结果字典
            grid_data = {}

            if img:
                # 根据产品类型选择波段
                if product == "MCD43A1":
                    bands = ['Band1_iso', 'Band1_vol', 'Band1_geo',
                             'Band2_iso', 'Band2_vol', 'Band2_geo']
                elif product == "MCD43A4":
                    bands = ['Nadir_Reflectance_Band1', 'Nadir_Reflectance_Band2']
                elif product == "MCD12Q1":
                    bands = ['LC_Type1']

                # 修复：使用单独的reduceRegions调用而不是设置多个输出
                # 为每个波段单独调用reduceRegions
                for band in bands:
                    # 区域统计
                    reduced = img.select([band]).reduceRegions(
                        collection=grid_fc,
                        reducer=ee.Reducer.mean(),
                        scale=500  # MODIS原始分辨率
                    )

                    # 获取结果
                    result_info = reduced.getInfo()

                    if 'features' in result_info:
                        for f in result_info['features']:
                            props = f['properties']
                            grid_x = props['grid_x']
                            grid_y = props['grid_y']
                            grid_key = (grid_x, grid_y)

                            if grid_key not in grid_data:
                                grid_data[grid_key] = {}

                            value = props.get('mean', -9999.0)
                            if value is None:
                                value = -9999.0
                            grid_data[grid_key][band] = value

            # 保存数据
            return save_raw_data(date, grid_data, stations, lats, lons, grid_info, station_to_grid, base_path, product)

        except Exception as e:
            retry_count += 1
            error_type = type(e).__name__
            logging.warning(f"处理 {date} {product} 时出错 ({error_type}): {e}，重试 {retry_count}/{max_retries}")
            time.sleep(5 * retry_count)  # 指数退避等待

            if retry_count >= max_retries:
                logging.error(f"处理 {date} {product} 失败，已达到最大重试次数")
                traceback.print_exc()
                return False


# 主函数
def main():
    # 初始化GEE
    GEE_authorizing()

    # 数据路径
    data_path = r"D:/H8_data"
    luts_path = os.path.join(data_path, "LUTs.nc")

    # 读取LUTs.nc文件
    stations, lats, lons = read_luts_nc(luts_path)
    logging.info(f"共读取 {len(stations)} 个站点")

    # 创建Himawari网格FeatureCollection
    grid_fc, grid_info, station_to_grid = get_feature_collection(stations, lats, lons)

    # 定义要下载的产品
    products = {
        "MCD12Q1": {
            "collection": ee.ImageCollection("MODIS/061/MCD12Q1"),
            "bands": ['LC_Type1'],
            "annual": True  # 年度产品
        },
        "MCD43A1": {
            "collection": ee.ImageCollection("MODIS/061/MCD43A1").select(
                ['BRDF_Albedo_Parameters_Band1_iso', 'BRDF_Albedo_Parameters_Band1_vol',
                 'BRDF_Albedo_Parameters_Band1_geo',
                 'BRDF_Albedo_Parameters_Band2_iso', 'BRDF_Albedo_Parameters_Band2_vol',
                 'BRDF_Albedo_Parameters_Band2_geo']
            ).map(lambda img: img.rename(['Band1_iso', 'Band1_vol', 'Band1_geo',
                                          'Band2_iso', 'Band2_vol', 'Band2_geo'])),
            "bands": ['Band1_iso', 'Band1_vol', 'Band1_geo', 'Band2_iso', 'Band2_vol', 'Band2_geo'],
            "annual": False
        },
        "MCD43A4": {
            "collection": ee.ImageCollection("MODIS/061/MCD43A4").select(
                ['Nadir_Reflectance_Band1', 'Nadir_Reflectance_Band2']
            ),
            "bands": ['Nadir_Reflectance_Band1', 'Nadir_Reflectance_Band2'],
            "annual": False
        }
    }

    # 设置日期范围
    start_date = datetime.date(2015, 7, 7)
    end_date = datetime.date(2024, 12, 31)

    # 生成日期序列
    all_dates = []
    current_date = start_date
    while current_date <= end_date:
        all_dates.append(current_date)
        current_date += datetime.timedelta(days=1)

    logging.info(f"日期范围: {start_date} 到 {end_date}, 共 {len(all_dates)} 天")

    # 处理每个产品
    for product, config in products.items():
        logging.info(f"开始处理产品: {product}")

        # 准备任务队列
        tasks = []
        for date in all_dates:
            # 如果是年度产品，只处理每年1月1日
            if config["annual"]:
                if date.month != 1 or date.day != 1:
                    continue

            # 检查文件是否已存在
            year = date.strftime("%Y")
            month = date.strftime("%m")
            filename = f"MODIS_RAW_{product}_{date.strftime('%Y%m%d')}.nc"
            dir_path = os.path.join(data_path, f"MODIS_RAW_{product}", year, month)
            file_path = os.path.join(dir_path, filename)

            # 如果文件不存在或不完整，则加入任务队列
            if not os.path.exists(file_path) or os.path.getsize(file_path) <= 1024:
                tasks.append(date)

        logging.info(f"产品 {product} 总任务数: {len(tasks)}")

        # 使用线程池并行处理
        success_count = 0
        failed_count = 0
        total_tasks = len(tasks)

        # 设置并行线程数
        max_workers = 3 if config["annual"] else 5

        with tqdm(total=total_tasks, desc=f"{product} 下载进度") as pbar:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {}
                for date in tasks:
                    future = executor.submit(
                        process_daily_raw_data,
                        date,
                        config["collection"],
                        grid_fc,
                        stations,
                        lats,
                        lons,
                        grid_info,
                        station_to_grid,
                        data_path,
                        product
                    )
                    futures[future] = date

                for future in concurrent.futures.as_completed(futures):
                    date = futures[future]
                    try:
                        result = future.result()
                        if result:
                            success_count += 1
                        else:
                            failed_count += 1
                    except Exception as e:
                        logging.error(f"任务处理异常: {e}")
                        failed_count += 1

                    pbar.update(1)
                    pbar.set_postfix_str(f"成功: {success_count}, 失败: {failed_count}")

        logging.info(f"产品 {product} 处理完成! 成功: {success_count}, 失败: {failed_count}")


if __name__ == "__main__":
    main()