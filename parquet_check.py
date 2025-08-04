import pyarrow.parquet as pq
import pyarrow as pa
import pandas as pd
import numpy as np
import os


def print_parquet_file_details(file_path):
    """打印Parquet文件的详细内容"""
    print(f"正在分析文件: {file_path}")

    if not os.path.exists(file_path):
        print(f"文件不存在: {file_path}")
        return

    try:
        # 读取Parquet文件
        parquet_file = pq.ParquetFile(file_path)

        # 打印文件基本信息
        print("\n=== 文件基本信息 ===")
        print(f"文件格式: Parquet")
        print(f"版本: {parquet_file.metadata.format_version}")
        print(f"创建者: {parquet_file.metadata.created_by}")
        print(f"行组数量: {parquet_file.num_row_groups}")
        print(f"总行数: {parquet_file.metadata.num_rows}")
        print(f"列数: {parquet_file.metadata.num_columns}")

        # 获取schema
        schema = parquet_file.schema_arrow

        # 打印Schema信息
        print("\n=== Schema信息 ===")
        print(schema)

        # 打印列详细信息
        print("\n=== 列详细信息 ===")
        # 正确获取字段数量
        field_count = len(schema.names)
        for i in range(field_count):
            field = schema.field(i)
            print(f"\n列名: {field.name}")
            print(f"  类型: {field.type}")
            print(f"  可为空: {field.nullable}")
            if field.metadata:
                print("  元数据:")
                for key, value in field.metadata.items():
                    # 处理字节串类型的元数据值
                    if isinstance(value, bytes):
                        try:
                            decoded_value = value.decode('utf-8')
                        except UnicodeDecodeError:
                            decoded_value = "<binary data>"
                    else:
                        decoded_value = str(value)
                    print(f"    {key}: {decoded_value}")

        # 读取前5行数据
        print("\n=== 前5行数据 ===")
        try:
            # 使用PyArrow读取前5行
            table = pq.read_table(
                file_path,
                use_threads=True,
                memory_map=True,
                columns=None,
                n_rows=5
            )
            df = table.to_pandas()

            # 格式化打印DataFrame
            with pd.option_context('display.max_columns', None,
                                   'display.width', None,
                                   'display.max_colwidth', 20):
                print(df)
        except Exception as e:
            print(f"读取数据时出错: {e}")

        # 打印列统计信息（基于元数据）
        print("\n=== 列统计信息（基于元数据）===")
        for rg in range(parquet_file.num_row_groups):
            row_group = parquet_file.metadata.row_group(rg)
            print(f"\n行组 {rg}:")
            print(f"  行数: {row_group.num_rows}")
            print(f"  总字节大小: {row_group.total_byte_size / 1024:.2f} KB")

            for col_idx in range(row_group.num_columns):
                col_meta = row_group.column(col_idx)
                stats = col_meta.statistics
                col_name = col_meta.path_in_schema
                print(f"\n  列: {col_name}")

                if stats is not None:
                    print(f"    最小值: {stats.min}")
                    print(f"    最大值: {stats.max}")
                    print(f"    空值数量: {stats.null_count}")
                    if stats.has_distinct_count:
                        print(f"    不同值数量: {stats.distinct_count}")
                else:
                    print("    无统计信息")
    except Exception as e:
        print(f"读取文件时出错: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    # 指定要查看的文件路径
    file_path = r"D:/H8_data/Correction_Records/Correction_Records_20150707_0200.parquet"

    # 打印文件详细信息
    print_parquet_file_details(file_path)

    # 添加等待输入，防止窗口立即关闭
    input("\n按Enter键退出...")