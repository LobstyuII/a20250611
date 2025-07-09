import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime

# 配置参数
INPUT_FILE = r"D:\H8_data\rain_events_all_stations.parquet"  # 输入文件路径


def analyze_rain_events(file_path):
    """
    分析降雨事件数据集并生成详细报告

    :param file_path: Parquet文件路径
    """
    # 1. 加载数据
    print(f"Loading data from {file_path}...")
    try:
        df = pd.read_parquet(file_path)
        print(f"Successfully loaded {len(df):,} records")
    except Exception as e:
        print(f"Error loading file: {e}")
        return

    # 2. 基本数据集信息
    print("\n===== Dataset Overview =====")
    print(f"Total records: {len(df):,}")
    print(f"Total stations: {df['Station'].nunique():,}")
    print(f"Time range: {df['Start_Time'].min()} to {df['End_Time'].max()}")
    print(f"Years covered: {df['Year'].unique()}")

    # 3. 数据结构信息
    print("\n===== Data Structure =====")
    print("Columns and data types:")
    print(df.dtypes)
    print("\nMissing values per column:")
    print(df.isnull().sum())

    # 4. 数值型变量分析
    print("\n===== Numerical Variables Analysis =====")
    num_cols = ['Duration_hours', 'Total_Rain_mm', 'Avg_Intensity_mmh',
                'Max_Intensity_mmh', 'Rainy_Hours']
    print(df[num_cols].describe().applymap(lambda x: f"{x:.2f}"))

    # 5. 分类变量分析
    print("\n===== Categorical Variables Analysis =====")
    print("Rain intensity class distribution:")
    class_dist = df['Intensity_Class'].value_counts(normalize=True) * 100
    print(class_dist.apply(lambda x: f"{x:.1f}%"))

    # 6. 时间序列分析
    print("\n===== Temporal Analysis =====")
    df['Start_YearMonth'] = df['Start_Time'].dt.to_period('M')
    monthly_events = df.groupby('Start_YearMonth').size()
    print("Events per month:")
    print(monthly_events.tail(12))  # 显示最近12个月

    # 7. 极端值检测
    print("\n===== Extreme Values Detection =====")
    print("Longest duration events:")
    print(df.nlargest(5, 'Duration_hours')[['Station', 'Start_Time', 'Duration_hours', 'Total_Rain_mm']])

    print("\nHighest total rainfall events:")
    print(df.nlargest(5, 'Total_Rain_mm')[['Station', 'Start_Time', 'Total_Rain_mm', 'Duration_hours']])

    print("\nHighest intensity events:")
    print(df.nlargest(5, 'Max_Intensity_mmh')[['Station', 'Start_Time', 'Max_Intensity_mmh', 'Total_Rain_mm']])

    # 8. 数据质量检查
    print("\n===== Data Quality Checks =====")
    # 检查持续时间是否合理
    calculated_duration = (df['End_Time'] - df['Start_Time']).dt.total_seconds() / 3600 + 1
    duration_diff = abs(df['Duration_hours'] - calculated_duration)
    print(f"Records with duration mismatch: {(duration_diff > 0.1).sum()}")

    # 检查降雨量与持续时间的关系
    invalid_rain = df[df['Total_Rain_mm'] < df['Rainy_Hours'] * 0.1]
    print(f"Records with potential rain measurement issues: {len(invalid_rain)}")

    # 9. 生成可视化报告
    print("\nGenerating visualizations...")
    plt.figure(figsize=(15, 10))

    # 降雨强度类别分布
    plt.subplot(2, 2, 1)
    sns.countplot(y='Intensity_Class', data=df, order=df['Intensity_Class'].value_counts().index)
    plt.title('Rain Intensity Class Distribution')
    plt.xlabel('Count')

    # 数值变量分布
    plt.subplot(2, 2, 2)
    sns.histplot(df['Total_Rain_mm'], bins=50, kde=True, log_scale=(True, False))
    plt.title('Total Rainfall Distribution (log scale)')
    plt.xlabel('Total Rainfall (mm)')

    # 时间序列趋势
    plt.subplot(2, 2, 3)
    monthly_events.plot(kind='line', marker='o')
    plt.title('Monthly Rain Events Count')
    plt.xlabel('Month')
    plt.ylabel('Number of Events')
    plt.grid(True)

    # 降雨量与持续时间关系
    plt.subplot(2, 2, 4)
    sns.scatterplot(data=df.sample(min(1000, len(df))),
                    x='Duration_hours',
                    y='Total_Rain_mm',
                    hue='Intensity_Class',
                    alpha=0.6)
    plt.title('Rainfall vs Duration')
    plt.xlabel('Duration (hours)')
    plt.ylabel('Total Rainfall (mm)')
    plt.xscale('log')
    plt.yscale('log')

    plt.tight_layout()

    # 保存报告
    report_file = file_path.replace('.parquet', '_report.png')
    plt.savefig(report_file, dpi=150)
    print(f"Visual report saved to: {report_file}")

    # 10. 保存分析摘要
    summary_file = file_path.replace('.parquet', '_summary.txt')
    with open(summary_file, 'w') as f:
        f.write(f"Rain Events Dataset Analysis Report\n")
        f.write(f"Generated on: {datetime.now()}\n\n")
        f.write(f"Dataset: {file_path}\n")
        f.write(f"Total records: {len(df):,}\n")
        f.write(f"Total stations: {df['Station'].nunique():,}\n")
        f.write(f"Time range: {df['Start_Time'].min()} to {df['End_Time'].max()}\n\n")
        f.write("Rain Intensity Class Distribution:\n")
        f.write(class_dist.to_string())
        f.write("\n\nTop 3 Stations by Event Count:\n")
        f.write(df['Station'].value_counts().head(3).to_string())

    print(f"Summary report saved to: {summary_file}")
    print("\nAnalysis completed!")


if __name__ == "__main__":
    analyze_rain_events(INPUT_FILE)