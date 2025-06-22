# 检查netcdf的格式和数据

import netCDF4 as nc
import numpy as np
import os


def print_nc_file_details(file_path):
    """打印NetCDF文件的详细内容"""
    print(f"正在分析文件: {file_path}")

    if not os.path.exists(file_path):
        print(f"文件不存在: {file_path}")
        return

    try:
        with nc.Dataset(file_path, 'r') as ds:
            # 打印文件基本信息
            print("\n=== 文件基本信息 ===")
            print(f"文件格式: {ds.data_model}")
            print(f"文件属性:")
            for attr in ds.ncattrs():
                print(f"  {attr}: {getattr(ds, attr)}")

            # 打印维度信息
            print("\n=== 维度信息 ===")
            for dim_name, dim in ds.dimensions.items():
                print(f"  {dim_name}: {len(dim)} ({'unlimited' if dim.isunlimited() else 'fixed'})")

            # 打印变量信息
            print("\n=== 变量信息 ===")
            for var_name, var in ds.variables.items():
                print(f"\n变量: {var_name}")
                print(f"  类型: {var.dtype}")
                print(f"  维度: {var.dimensions}")
                print(f"  形状: {var.shape}")

                # 打印变量属性
                if var.ncattrs():
                    print("  属性:")
                    for attr in var.ncattrs():
                        print(f"    {attr}: {getattr(var, attr)}")

                # 打印前5个数据点（如果是Station维度）
                if 'Station' in var.dimensions:
                    print("  前5个数据点:")
                    try:
                        # 直接获取数据，不需要额外解码
                        data = var[:5]

                        # 如果是字符串类型，直接打印
                        if var.dtype.kind in ['S', 'U']:  # S=bytes, U=unicode
                            print(f"    {list(data)}")
                        else:
                            print(f"    {data}")
                    except Exception as e:
                        print(f"    读取数据出错: {e}")

            # 打印前5个站点的所有变量值
            print("\n=== 前5个站点的数据值 ===")
            try:
                # 直接获取站点名称，不需要解码
                station_names = ds['Station'][:5]
                print("站点名称:", station_names)

                # 列出所有数据变量（排除Station本身）
                data_vars = [v for v in ds.variables if v != 'Station']

                for var_name in data_vars:
                    print(f"\n变量: {var_name}")
                    data = ds[var_name][:5]  # 前5个站点
                    print(f"  值: {data}")

            except Exception as e:
                print(f"读取站点数据出错: {e}")

            # 打印全局统计信息
            print("\n=== 全局统计信息 ===")
            for var_name in ds.variables:
                if var_name != 'Station' and ds.variables[var_name].dtype.kind not in ['S', 'U']:
                    var = ds.variables[var_name]
                    print(f"{var_name}:")
                    data = var[:]
                    print(f"  最小值: {np.nanmin(data):.4f}")
                    print(f"  最大值: {np.nanmax(data):.4f}")
                    print(f"  平均值: {np.nanmean(data):.4f}")
                    print(f"  缺失值数量: {np.sum(np.isnan(data))}")
                    print(f"  有效值比例: {1 - np.sum(np.isnan(data)) / data.size:.2%}")

    except Exception as e:
        print(f"读取文件时出错: {e}")


if __name__ == "__main__":
    # 指定要查看的文件路径
    file_path = r"D:\\H8_data\\H8L1\\2015\\08\\H8_monthly_201508.nc"

    # 打印文件详细信息
    print_nc_file_details(file_path)

    # 添加等待输入，防止窗口立即关闭
    input("\n按Enter键退出...")
