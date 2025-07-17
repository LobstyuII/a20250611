import os
import netCDF4 as nc
import numpy as np
from datetime import datetime

# 配置路径
MERRA2_ROOT = "D:/H8_data/MERRA2/"
REFORMATTED_ROOT = "D:/H8_data/MERRA2_Reformatted/"
YEARS_TO_PROCESS = ["2018", "2019", "2020"]  # 根据您的数据范围调整


def reformat_merra2_file(file_path, output_path):
    """将MERRA2文件中的二维数组转换为一维数组"""
    try:
        with nc.Dataset(file_path) as src:
            # 创建输出文件
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with nc.Dataset(output_path, 'w') as dst:
                # 复制全局属性
                dst.setncatts(src.__dict__)

                # 创建维度 - 只保留Station维度
                dst.createDimension('Station', src.dimensions['Station'].size)

                # 复制Station变量
                station_var = dst.createVariable('Station', src.variables['Station'].dtype, ('Station',))
                station_var[:] = src.variables['Station'][:]
                station_var.setncatts(src.variables['Station'].__dict__)

                # 复制Lat变量
                lat_var = dst.createVariable('Lat', src.variables['Lat'].dtype, ('Station',))
                lat_var[:] = src.variables['Lat'][:]
                lat_var.setncatts(src.variables['Lat'].__dict__)

                # 复制Lon变量
                lon_var = dst.createVariable('Lon', src.variables['Lon'].dtype, ('Station',))
                lon_var[:] = src.variables['Lon'][:]
                lon_var.setncatts(src.variables['Lon'].__dict__)

                # 处理TO3变量 - 从二维转换为一维
                to3_src = src.variables['TO3']

                # 先创建变量并设置属性（包括_FillValue）
                to3_dst = dst.createVariable('TO3', to3_src.dtype, ('Station',))

                # 设置属性（在赋值前）
                to3_dst.setncatts(to3_src.__dict__)

                # 检查并转换数据
                if to3_src.ndim == 2 and to3_src.shape[0] == 1:
                    to3_dst[:] = to3_src[0, :]  # 取第一个时间步
                else:
                    print(f"警告: TO3维度异常 ({to3_src.shape})，尝试直接复制")
                    to3_dst[:] = to3_src[:]

                # 处理TQV变量 - 从二维转换为一维
                tqv_src = src.variables['TQV']

                # 先创建变量并设置属性（包括_FillValue）
                tqv_dst = dst.createVariable('TQV', tqv_src.dtype, ('Station',))

                # 设置属性（在赋值前）
                tqv_dst.setncatts(tqv_src.__dict__)

                # 检查并转换数据
                if tqv_src.ndim == 2 and tqv_src.shape[0] == 1:
                    tqv_dst[:] = tqv_src[0, :]  # 取第一个时间步
                else:
                    print(f"警告: TQV维度异常 ({tqv_src.shape})，尝试直接复制")
                    tqv_dst[:] = tqv_src[:]

                # 添加处理信息
                dst.date_modified = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                dst.process_note = "MERRA2数据格式标准化 - 移除时间维度"

        print(f"成功转换: {file_path} -> {output_path}")
        return True

    except Exception as e:
        print(f"处理文件 {file_path} 时出错: {str(e)}")
        return False


def process_merra2_directory():
    """处理所有MERRA2文件"""
    total_files = 0
    processed_files = 0
    error_files = 0

    for year in YEARS_TO_PROCESS:
        year_path = os.path.join(MERRA2_ROOT, year)
        if not os.path.exists(year_path):
            print(f"跳过不存在的年份目录: {year_path}")
            continue

        for month in os.listdir(year_path):
            month_path = os.path.join(year_path, month)
            if not os.path.isdir(month_path):
                continue

            for file_name in os.listdir(month_path):
                if file_name.endswith(".nc"):
                    src_path = os.path.join(month_path, file_name)
                    total_files += 1

                    # 创建对应的输出路径
                    dest_path = os.path.join(
                        REFORMATTED_ROOT,
                        year,
                        month,
                        file_name
                    )

                    # 处理文件
                    if reformat_merra2_file(src_path, dest_path):
                        processed_files += 1
                    else:
                        error_files += 1

    print(f"\n处理完成! 成功: {processed_files}, 失败: {error_files}, 总计: {total_files} 个文件")
    print(f"格式化后的文件保存在: {REFORMATTED_ROOT}")


if __name__ == "__main__":
    # 确保输出目录存在
    os.makedirs(REFORMATTED_ROOT, exist_ok=True)

    print("开始处理MERRA2文件格式标准化...")
    process_merra2_directory()
    print("处理完成!")