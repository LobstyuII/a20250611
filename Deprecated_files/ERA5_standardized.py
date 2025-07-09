import os
import xarray as xr
import numpy as np
from tqdm import tqdm
import shutil

# 配置路径
base_path = "D:/H8_data"
source_dir = os.path.join(base_path, "ERA5")
target_dir = os.path.join(base_path, "ERA5_Reformatted")


def reformat_era5_files(source_dir, target_dir):
    """重新格式化ERA5文件，删除时间维度并展平变量"""
    # 收集所有源文件
    all_files = []
    for root, dirs, files in os.walk(source_dir):
        for file in files:
            if file.endswith(".nc") and file.startswith("ERA5_"):
                all_files.append(os.path.join(root, file))

    if not all_files:
        print("未找到ERA5数据文件")
        return

    print(f"找到 {len(all_files)} 个文件，开始重新格式化...")

    # 处理每个文件
    for src_path in tqdm(all_files, desc="处理文件"):
        try:
            # 构建目标路径（保持相同目录结构）
            rel_path = os.path.relpath(src_path, source_dir)
            dst_path = os.path.join(target_dir, rel_path)
            os.makedirs(os.path.dirname(dst_path), exist_ok=True)

            # 打开源数据集
            with xr.open_dataset(src_path) as ds:
                # 创建新数据集
                new_ds = xr.Dataset()

                # 复制站点坐标数据
                new_ds["Station"] = ds["Station"]
                new_ds["Lat"] = ds["Lat"]
                new_ds["Lon"] = ds["Lon"]

                # 处理每个气象变量
                variables = [
                    'dewpoint_temperature_2m',
                    'temperature_2m',
                    'surface_pressure',
                    'total_precipitation',
                    'u_component_of_wind_10m',
                    'v_component_of_wind_10m'
                ]

                for var in variables:
                    # 移除时间维度并展平为1D数组
                    new_ds[var] = ds[var].squeeze(dim="time", drop=True)

                # 添加时间属性作为全局属性
                time_str = str(ds.time.values[0])
                new_ds.attrs["original_time"] = time_str

                # 保存新文件
                new_ds.to_netcdf(dst_path)

        except Exception as e:
            print(f"处理文件 {src_path} 时出错: {e}")
            # 复制原始文件作为后备
            shutil.copy2(src_path, dst_path)
            print(f"已复制原始文件到 {dst_path}")

    print("重新格式化完成！")


if __name__ == "__main__":
    reformat_era5_files(source_dir, target_dir)