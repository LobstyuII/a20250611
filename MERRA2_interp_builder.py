import os
import logging
import numpy as np
import netCDF4 as nc
from datetime import datetime, timedelta
from tqdm import tqdm
import concurrent.futures
import shutil

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler()]
)


class MERRA2Interpolator:
    def __init__(self, base_path, interp_path, start_date=None, end_date=None):
        """
        初始化MERRA2插值器

        :param base_path: 原始MERRA2数据存储根目录
        :param interp_path: 插值数据存储根目录
        :param start_date: 插值起始日期 (YYYYMMDD)
        :param end_date: 插值结束日期 (YYYYMMDD)
        """
        self.base_path = base_path
        self.interp_path = interp_path
        self.start_date = start_date
        self.end_date = end_date
        self.file_cache = {}
        self.stations = None
        self.lats = None
        self.lons = None
        self.num_stations = None

        # 创建插值目录
        os.makedirs(interp_path, exist_ok=True)

    def initialize(self):
        """初始化，获取站点信息"""
        # 从样本文件获取站点信息
        sample_file = self.find_sample_file()
        if not sample_file:
            raise FileNotFoundError("无法找到有效的MERRA2样本文件")

        with nc.Dataset(sample_file, 'r') as src:
            self.stations = src['Station'][:]
            self.lats = src['Lat'][:]
            self.lons = src['Lon'][:]
            self.num_stations = len(self.stations)

        logging.info(f"成功获取站点信息，共 {self.num_stations} 个站点")

    def find_sample_file(self):
        """查找有效的样本文件以获取站点信息"""
        # 尝试找到第一个可用的文件
        for year in range(2015, 2021):
            for month in range(1, 13):
                dir_path = os.path.join(self.base_path, "MERRA2", str(year), f"{month:02d}")
                if os.path.exists(dir_path):
                    for file in os.listdir(dir_path):
                        if file.startswith("MERRA2_") and file.endswith("_TO3_TQV.nc"):
                            return os.path.join(dir_path, file)
        return None

    def get_hourly_data(self, target_time):
        """
        获取整点数据并自动缓存

        :param target_time: 目标时间 (datetime对象)
        :return: 包含TO3和TQV数据的字典
        """
        hour_key = target_time.strftime("%Y%m%d_%H00")

        # 尝试从缓存获取
        if hour_key in self.file_cache:
            return self.file_cache[hour_key]

        # 构建文件路径
        year = target_time.strftime("%Y")
        month = target_time.strftime("%m")
        filename = f"MERRA2_{hour_key}_TO3_TQV.nc"
        file_path = os.path.join(self.base_path, "MERRA2", year, month, filename)

        if not os.path.exists(file_path):
            logging.warning(f"文件不存在: {file_path}")
            # 创建缺失数据占位符
            missing_data = {
                'time': (target_time - datetime(1980, 1, 1)).total_seconds(),
                'TO3': np.full(self.num_stations, -9999.0),
                'TQV': np.full(self.num_stations, -9999.0)
            }
            self.file_cache[hour_key] = missing_data
            return missing_data

        try:
            with nc.Dataset(file_path, 'r') as ds:
                # 读取时间并转换为秒
                hours_since_1980 = ds['time'][0]
                time_seconds = hours_since_1980 * 3600.0

                data = {
                    'time': time_seconds,
                    'TO3': ds['TO3'][0, :],
                    'TQV': ds['TQV'][0, :]
                }

            # 更新缓存
            self.file_cache[hour_key] = data

            # 限制缓存大小 (最多保留最近48小时)
            if len(self.file_cache) > 48:
                oldest_key = next(iter(self.file_cache))
                del self.file_cache[oldest_key]

            return data

        except Exception as e:
            logging.error(f"读取文件 {file_path} 失败: {e}")
            # 返回缺失数据
            return {
                'time': (target_time - datetime(1980, 1, 1)).total_seconds(),
                'TO3': np.full(self.num_stations, -9999.0),
                'TQV': np.full(self.num_stations, -9999.0)
            }

    def generate_time_points(self):
        """生成10分钟间隔的时间点"""
        # 默认时间范围 (2015-2021)
        start = datetime(2015, 7, 7) if not self.start_date else datetime.strptime(self.start_date, "%Y%m%d")
        end = datetime(2021, 12, 31, 23, 50) if not self.end_date else datetime.strptime(self.end_date,
                                                                                         "%Y%m%d") + timedelta(
            days=1) - timedelta(minutes=10)

        # 计算总点数
        total_points = int((end - start).total_seconds() / 600) + 1
        logging.info(f"生成时间点: {start} 到 {end}, 共 {total_points} 个10分钟间隔")

        # 生成时间序列
        current = start
        while current <= end:
            yield current
            current += timedelta(minutes=10)

    def create_output_dir(self, dt):
        """创建输出目录并返回文件路径"""
        year = dt.strftime("%Y")
        month = dt.strftime("%m")
        dir_path = os.path.join(self.interp_path, year, month)
        os.makedirs(dir_path, exist_ok=True)

        # 文件名格式: MERRA2_interp_YYYYMMDD_HHMM_TO3_TQV.nc
        filename = f"MERRA2_interp_{dt.strftime('%Y%m%d_%H%M')}_TO3_TQV.nc"
        return os.path.join(dir_path, filename)

    def write_10min_file(self, dt, to3_data, tqv_data):
        """写入10分钟分辨率数据文件"""
        output_path = self.create_output_dir(dt)

        # 检查文件是否已存在
        if os.path.exists(output_path):
            return

        with nc.Dataset(output_path, 'w', format='NETCDF4') as ds:
            # 定义维度
            ds.createDimension('Station', self.num_stations)
            ds.createDimension('time', 1)

            # 计算最大字符串长度
            max_str_len = max(len(str(s)) for s in self.stations) + 1

            # 定义变量
            time_var = ds.createVariable('time', 'f8', ('time',))
            station_var = ds.createVariable('Station', f'S{max_str_len}', ('Station',))
            lat_var = ds.createVariable('Lat', 'f4', ('Station',))
            lon_var = ds.createVariable('Lon', 'f4', ('Station',))
            to3_var = ds.createVariable('TO3', 'f4', ('time', 'Station'), fill_value=-9999.0)
            tqv_var = ds.createVariable('TQV', 'f4', ('time', 'Station'), fill_value=-9999.0)

            # 设置属性
            time_var.units = 'hours since 1980-01-01 00:00:00'
            time_var.calendar = 'standard'
            to3_var.units = 'Dobson'
            to3_var.long_name = 'Total Column Ozone'
            tqv_var.units = 'kg/m^2'
            tqv_var.long_name = 'Total Precipitable Water Vapor'

            # 转换时间格式
            ref_time = datetime(1980, 1, 1)
            hours_since_ref = (dt - ref_time).total_seconds() / 3600.0

            # 写入数据
            time_var[:] = hours_since_ref

            # 处理字符串数据
            station_arr = np.array([np.string_(str(s)) for s in self.stations], dtype=f'S{max_str_len}')
            station_var[:] = station_arr
            lat_var[:] = self.lats
            lon_var[:] = self.lons
            to3_var[0, :] = to3_data
            tqv_var[0, :] = tqv_data

    def interpolate_time_point(self, dt):
        """处理单个时间点的插值"""
        if dt.minute == 0:  # 整点时刻
            data = self.get_hourly_data(dt)
            to3_val = data['TO3']
            tqv_val = data['TQV']
        else:  # 插值时刻
            prev_hour = dt.replace(minute=0)
            next_hour = prev_hour + timedelta(hours=1)

            data_prev = self.get_hourly_data(prev_hour)
            data_next = self.get_hourly_data(next_hour)

            # 计算权重 (0~1)
            weight = (dt - prev_hour).total_seconds() / 3600.0

            # 线性插值
            to3_val = (1 - weight) * data_prev['TO3'] + weight * data_next['TO3']
            tqv_val = (1 - weight) * data_prev['TQV'] + weight * data_next['TQV']

            # 处理缺失值
            mask = (data_prev['TO3'] == -9999) | (data_next['TO3'] == -9999)
            to3_val[mask] = -9999
            tqv_val[mask] = -9999

        # 写入文件
        self.write_10min_file(dt, to3_val, tqv_val)

        return dt

    def run(self, max_workers=4):
        """执行插值过程"""
        try:
            # 初始化站点信息
            self.initialize()

            # 获取时间点生成器
            time_points = list(self.generate_time_points())
            total_points = len(time_points)
            logging.info(f"开始处理 {total_points} 个时间点...")

            # 使用进程池并行处理
            with tqdm(total=total_points, desc="生成10分钟分辨率数据") as pbar:
                with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
                    # 提交任务
                    futures = {executor.submit(self.interpolate_time_point, dt): dt for dt in time_points}

                    # 处理结果
                    for future in concurrent.futures.as_completed(futures):
                        try:
                            dt = future.result()
                            pbar.update(1)
                        except Exception as e:
                            logging.error(f"处理时间点 {futures[future]} 失败: {e}")
                            pbar.update(1)

            logging.info(f"处理完成! 结果保存在 {self.interp_path}")

        except Exception as e:
            logging.error(f"插值过程失败: {e}")
            raise


def main():
    # 配置路径和参数
    base_path = "D:/H8_data"  # 原始数据存储路径
    interp_path = "D:/H8_data/MERRA2_interp"  # 插值数据存储路径

    # 可选：指定插值时间范围 (格式: YYYYMMDD)
    start_date = "20150707"
    end_date = "20161231"
    # start_date = None  # 使用默认范围 (2015-2021)
    # end_date = None

    # 创建并运行插值器
    interpolator = MERRA2Interpolator(base_path, interp_path, start_date, end_date)
    interpolator.run(max_workers=6)  # 根据CPU核心数调整


if __name__ == "__main__":
    main()