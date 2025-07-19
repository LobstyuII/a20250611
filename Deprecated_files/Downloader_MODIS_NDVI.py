import ee
import pandas as pd
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

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler()]
)


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


def read_luts_nc(luts_path):
    """从LUTs.nc文件中读取站点信息"""
    try:
        ds = xr.open_dataset(luts_path)
        logging.info(f"成功读取 LUTs.nc 文件")

        # 获取站点信息
        stations = ds['Station'].values
        lats = ds['Lat'].values
        lons = ds['Lon'].values

        return stations, lats, lons

    except Exception as e:
        logging.error(f"读取 LUTs.nc 文件失败: {e}")
        raise


def get_himawari_grid(lon, lat):
    """
    计算Himawari 5km网格的边界和索引
    公式:
        longitude = 80 + x * 0.05
        latitude = 60 - y * 0.05
    """
    # 计算网格索引
    x_index = math.floor((lon - 80) / 0.05)
    y_index = math.floor((60 - lat) / 0.05)

    # 计算网格边界
    west = 80 + x_index * 0.05
    east = west + 0.05
    north = 60 - y_index * 0.05
    south = north - 0.05

    return west, south, east, north, x_index, y_index


def get_feature_collection(stations, lats, lons):
    """创建Himawari 5km网格的FeatureCollection"""
    try:
        features = []
        grid_info = []  # 存储网格索引信息

        for station, lat, lon in zip(stations, lats, lons):
            # 计算Himawari网格
            west, south, east, north, x_index, y_index = get_himawari_grid(lon, lat)

            # 创建矩形特征
            rect = ee.Geometry.Rectangle([west, south, east, north])
            feature = ee.Feature(
                rect,
                {
                    'Station': station,
                    'grid_x': x_index,
                    'grid_y': y_index
                }
            )
            features.append(feature)
            grid_info.append((x_index, y_index))

        fc = ee.FeatureCollection(features)
        logging.info("成功创建Himawari网格FeatureCollection")
        return fc, grid_info

    except Exception as e:
        logging.error(f"创建FeatureCollection失败: {e}")
        raise


def save_daily_data(date, terra_data, aqua_data, stations, lats, lons, grid_info, base_path):
    """保存单日数据到NC文件（新增网格索引）"""
    try:
        # 创建年月目录
        year = date.strftime("%Y")
        month = date.strftime("%m")
        dir_path = os.path.join(base_path, "MODIS_NDVI", year, month)
        os.makedirs(dir_path, exist_ok=True)

        # 文件路径
        filename = f"MODIS_NDVI_{date.strftime('%Y%m%d')}.nc"
        file_path = os.path.join(dir_path, filename)

        # 如果文件已存在且完整，则跳过
        if os.path.exists(file_path) and os.path.getsize(file_path) > 1024:
            logging.info(f"文件已存在: {file_path}")
            return True

        # 创建新的NC文件
        with nc.Dataset(file_path, 'w', format='NETCDF4') as ds:
            # 定义维度（只有站点维度，没有时间维度）
            ds.createDimension('Station', len(stations))

            # 定义变量
            station_var = ds.createVariable('Station', str, ('Station',))
            lat_var = ds.createVariable('Lat', 'f4', ('Station',))
            lon_var = ds.createVariable('Lon', 'f4', ('Station',))
            terra_var = ds.createVariable('NDVI_Terra', 'f4', ('Station',), fill_value=-9999.0)
            aqua_var = ds.createVariable('NDVI_Aqua', 'f4', ('Station',), fill_value=-9999.0)

            # 新增网格索引变量
            gridx_var = ds.createVariable('grid_x', 'i4', ('Station',))
            gridy_var = ds.createVariable('grid_y', 'i4', ('Station',))

            # 添加日期作为全局属性
            ds.date = date.strftime("%Y-%m-%d")

            # 写入站点数据
            station_var[:] = np.array(stations, dtype=object)
            lat_var[:] = lats
            lon_var[:] = lons

            # 写入网格索引数据
            gridx = [g[0] for g in grid_info]
            gridy = [g[1] for g in grid_info]
            gridx_var[:] = gridx
            gridy_var[:] = gridy

            # 写入NDVI数据（一维数组）
            terra_var[:] = terra_data
            aqua_var[:] = aqua_data

        logging.info(f"成功保存: {file_path}")
        return True

    except Exception as e:
        logging.error(f"保存 {date} 数据失败: {e}")
        traceback.print_exc()
        return False


def process_daily_data(date, terra_col, aqua_col, grid_fc, stations, lats, lons, grid_info, base_path, max_retries=5):
    """处理单日数据（使用区域统计替代点采样）"""
    retry_count = 0
    while retry_count < max_retries:
        try:
            # 设置日期范围（UTC时间）
            start_date = datetime.datetime(date.year, date.month, date.day, 0, 0, 0)
            end_date = start_date + datetime.timedelta(days=1)

            # 获取Terra数据（使用区域统计）
            terra_img = terra_col.filterDate(start_date, end_date).first()
            terra_data = [-9999.0] * len(stations)

            if terra_img:
                terra_reduced = terra_img.reduceRegions(
                    collection=grid_fc,
                    reducer=ee.Reducer.mean(),
                    scale=500  # MODIS原始分辨率
                )
                terra_info = terra_reduced.getInfo()

                if 'features' in terra_info:
                    # 构建站点到NDVI的映射
                    temp_data = {}
                    for f in terra_info['features']:
                        props = f['properties']
                        station = props['Station']
                        ndvi = props.get('mean', -9999.0)
                        if ndvi is None:  # 处理空值
                            ndvi = -9999.0
                        temp_data[station] = ndvi

                    terra_data = [temp_data.get(station, -9999.0) for station in stations]

            # 获取Aqua数据（同样使用区域统计）
            aqua_img = aqua_col.filterDate(start_date, end_date).first()
            aqua_data = [-9999.0] * len(stations)

            if aqua_img:
                aqua_reduced = aqua_img.reduceRegions(
                    collection=grid_fc,
                    reducer=ee.Reducer.mean(),
                    scale=500
                )
                aqua_info = aqua_reduced.getInfo()

                if 'features' in aqua_info:
                    temp_data = {}
                    for f in aqua_info['features']:
                        props = f['properties']
                        station = props['Station']
                        ndvi = props.get('mean', -9999.0)
                        if ndvi is None:
                            ndvi = -9999.0
                        temp_data[station] = ndvi

                    aqua_data = [temp_data.get(station, -9999.0) for station in stations]

            # 保存数据（新增grid_info参数）
            return save_daily_data(date, terra_data, aqua_data, stations, lats, lons, grid_info, base_path)

        except Exception as e:
            retry_count += 1
            error_type = type(e).__name__
            logging.warning(f"处理 {date} 时出错 ({error_type}): {e}，重试 {retry_count}/{max_retries}")
            time.sleep(5 * retry_count)  # 指数退避等待

            if retry_count >= max_retries:
                logging.error(f"处理 {date} 失败，已达到最大重试次数")
                traceback.print_exc()
                return False


def main():
    # 初始化 GEE
    GEE_authorizing()

    # 数据路径
    data_path = r"D:/H8_data"
    luts_path = os.path.join(data_path, "LUTs.nc")

    # 读取LUTs.nc文件（只获取站点信息）
    stations, lats, lons = read_luts_nc(luts_path)
    logging.info(f"共读取 {len(stations)} 个站点")

    # 创建Himawari网格FeatureCollection并获取网格信息
    grid_fc, grid_info = get_feature_collection(stations, lats, lons)

    # 定义GEE ImageCollection
    terra_col = ee.ImageCollection("MODIS/MOD09GA_006_NDVI").select('NDVI')
    aqua_col = ee.ImageCollection("MODIS/MYD09GA_006_NDVI").select('NDVI')
    logging.info("已初始化Terra和Aqua NDVI集合")

    # 设置日期范围（示例日期）
    start_date = datetime.date(2022, 1, 1)
    end_date = datetime.date(2024, 12, 31)

    # 生成日期序列
    unique_dates = []
    current_date = start_date
    while current_date <= end_date:
        unique_dates.append(current_date)
        current_date += datetime.timedelta(days=1)

    logging.info(f"日期范围: {start_date} 到 {end_date}, 共 {len(unique_dates)} 天")

    # 准备任务队列
    tasks = []
    for date in unique_dates:
        # 检查文件是否已存在
        year = date.strftime("%Y")
        month = date.strftime("%m")
        filename = f"MODIS_NDVI_{date.strftime('%Y%m%d')}.nc"
        file_path = os.path.join(data_path, "MODIS_NDVI", year, month, filename)

        # 如果文件不存在或不完整，则加入任务队列
        if not os.path.exists(file_path) or os.path.getsize(file_path) <= 1024:
            tasks.append(date)

    logging.info(f"总日期数: {len(unique_dates)}, 已存在: {len(unique_dates) - len(tasks)}, 待处理: {len(tasks)}")

    # 使用线程池并行处理
    success_count = 0
    failed_count = 0
    total_tasks = len(tasks)

    # 设置并行线程数（根据GEE配额调整）
    max_workers = 5  # 保守设置避免超过配额

    with tqdm(total=total_tasks, desc="下载进度") as pbar:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交所有任务
            futures = {executor.submit(
                process_daily_data,
                date, terra_col, aqua_col, grid_fc, stations, lats, lons, grid_info, data_path
            ): date for date in tasks}

            # 处理完成的任务
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

    logging.info(f"处理完成! 成功: {success_count}, 失败: {failed_count}, 总数: {total_tasks}")


def merge_modis_data(base_path, output_path):
    """合并所有日数据到单个NetCDF文件"""
    try:
        # 收集所有文件路径
        all_files = []
        modis_dir = os.path.join(base_path, "MODIS_NDVI")

        for root, dirs, files in os.walk(modis_dir):
            for file in files:
                if file.endswith(".nc") and file.startswith("MODIS_NDVI_"):
                    all_files.append(os.path.join(root, file))

        if not all_files:
            logging.error("未找到MODIS NDVI数据文件")
            return

        logging.info(f"找到 {len(all_files)} 个数据文件，开始合并...")

        # 按文件名排序（即按时间排序）
        all_files.sort(key=lambda x: os.path.basename(x).split('_')[2][:8])

        # 使用xarray打开并合并文件
        ds_list = []
        for file in tqdm(all_files, desc="合并文件"):
            try:
                ds = xr.open_dataset(file)
                # 从全局属性中获取日期并转换为时间坐标
                date_str = ds.attrs['date']
                ds = ds.assign_coords(time=pd.to_datetime(date_str))
                ds = ds.expand_dims('time')
                ds_list.append(ds)
            except Exception as e:
                logging.warning(f"无法打开文件 {file}: {e}")

        if not ds_list:
            logging.error("没有有效文件可合并")
            return

        # 沿时间维度合并
        combined = xr.concat(ds_list, dim="time")

        # 关闭所有文件
        for ds in ds_list:
            ds.close()

        # 保存合并后的数据集
        combined.to_netcdf(output_path)
        logging.info(f"成功合并数据到: {output_path}")

        # 验证文件
        try:
            ds = xr.open_dataset(output_path)
            logging.info(f"合并后数据集信息: \n{ds}")
            ds.close()
        except Exception as e:
            logging.error(f"验证输出文件失败: {e}")

    except Exception as e:
        logging.error(f"合并数据失败: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    # 第一步：下载数据
    main()

    # 第二步：合并数据（下载完成后运行）
    # data_path = "D:/H8_data"
    # output_nc = os.path.join(data_path, "MODIS_NDVI_combined.nc")
    # merge_modis_data(data_path, output_nc)