import os
import pandas as pd
import numpy as np
from netCDF4 import Dataset
import logging
import traceback

# 配置日志
logging.basicConfig(filename='conversion.log', level=logging.ERROR,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# 定义常量
INPUT_DIR = r'D:\H8_data\Airdata_raw'
OUTPUT_BASE = r'D:\H8_data\Air'
VAR_LIST = [
    'AQI', 'PM2.5', 'PM2.5_24h', 'PM10', 'PM10_24h',
    'SO2', 'SO2_24h', 'NO2', 'NO2_24h', 'O3',
    'O3_24h', 'O3_8h', 'O3_8h_24h', 'CO', 'CO_24h'
]


def process_file(csv_path):
    """处理单个CSV文件"""
    try:
        # 从文件名提取日期
        filename = os.path.basename(csv_path)
        date_str = filename.split('_')[2].split('.')[0]
        year = date_str[:4]
        month = date_str[4:6]

        # 创建输出目录
        output_dir = os.path.join(OUTPUT_BASE, year, month)
        os.makedirs(output_dir, exist_ok=True)

        # 读取CSV文件
        df = pd.read_csv(csv_path, dtype={'date': str, 'hour': int, 'type': str})

        # 获取站点列表（排除前3列）
        stations = [col for col in df.columns if col not in ['date', 'hour', 'type']]

        # 处理每个小时
        for hour in range(24):
            try:
                # 筛选当前小时的数据
                hour_df = df[df['hour'] == hour]
                if hour_df.empty:
                    logging.warning(f"No data for hour {hour} in {filename}")
                    continue

                # 创建NetCDF文件
                nc_filename = f"Air_{date_str}_{hour:02d}00.nc"
                nc_path = os.path.join(output_dir, nc_filename)

                with Dataset(nc_path, 'w', format='NETCDF4') as nc:
                    # 创建维度
                    nc.createDimension('Station', len(stations))

                    # 添加站点变量
                    station_var = nc.createVariable('Station', str, ('Station',))
                    station_var[:] = np.array(stations, dtype=object)

                    # 添加其他变量
                    for var_name in VAR_LIST:
                        var_data = hour_df[hour_df['type'] == var_name]

                        if not var_data.empty:
                            # 获取数据值（处理空值）
                            values = var_data[stations].values[0]
                            values = [np.nan if x == '' or x == ' ' else float(x) for x in values]
                        else:
                            values = [np.nan] * len(stations)

                        # 创建变量
                        nc_var = nc.createVariable(
                            var_name, 'f4', ('Station',),
                            fill_value=-9999.0,
                            zlib=True
                        )
                        nc_var[:] = values

                print(f"Created: {nc_path}")

            except Exception as e:
                logging.error(f"Error processing hour {hour} in {filename}: {traceback.format_exc()}")

    except pd.errors.EmptyDataError:
        logging.error(f"Empty CSV file: {csv_path}")
    except Exception as e:
        logging.error(f"Error processing {csv_path}: {traceback.format_exc()}")


def main():
    """主处理函数"""
    for filename in os.listdir(INPUT_DIR):
        if filename.endswith('.csv') and filename.startswith('china_sites_'):
            csv_path = os.path.join(INPUT_DIR, filename)
            try:
                print(f"Processing: {filename}")
                process_file(csv_path)
            except Exception as e:
                logging.error(f"Fatal error with {filename}: {traceback.format_exc()}")


if __name__ == "__main__":
    main()