H8L3ARP卫星数据文件说明
====================

1. 文件命名规则
   - 格式: H8L3ARP_YYYYMMDD_HH00.nc
     示例: H8L3ARP_20150801_0200.nc
   - 说明:
     * YYYY: 年份 (4位数字)
     * MM: 月份 (2位数字)
     * DD: 日期 (2位数字)
     * HH: 小时 (UTC时间，2位数字)
     * 00: 分钟 (固定为00，表示整点数据)

2. 文件格式
   - 格式类型: NetCDF-4
   - 维度: 1 (站点维度)
   - 变量: 5个
   - 文件大小: 约150-250 KB

3. 数据内容
   | 变量名             | 描述                                 | 单位 | 数据类型 | 维度         |
   |--------------------|--------------------------------------|------|----------|--------------|
   | Station            | 站点名称                             | 无   | 字符串   | Station(2014)|
   | Data_Availability  | 数据可用性标志 (0:不可用, 1:可用)    | 无   | int8     | Station(2014)|
   | Land_Water_Flag    | 陆地/水体标志 (0:水体, 1:陆地)       | 无   | int8     | Station(2014)|
   | Cloud_Flag         | 云标志 (0:无云, 1:有云)              | 无   | int8     | Station(2014)|
   | AOT                | 500nm气溶胶光学厚度                  | 无   | float32  | Station(2014)|
   | AOT_Uncertainty    | 气溶胶光学厚度不确定性               | 无   | float32  | Station(2014)|

4. 数据处理说明
   - 数据提取:
     * 从L3ARP产品中提取每个站点的数据
     * 提取了QA_flag_merged的三个比特位(数据可用性、陆地水体标志、云标志)
     * 提取了500nm气溶胶光学厚度(AOT_L2_Mean)及其不确定性(AOT_Merged_uncertainty)
   - 数据质量:
     * Data_Availability为0表示该站点数据不可用(可能是由于云、无效值等原因)
     * 当Data_Availability为0时，AOT值可能为无效值(通常为-9999)
     * 有效AOT范围: 0.0 - 5.0(但可能有异常值)
   - 时间表示:
     * 全局属性: time = "0200" (表示02:00 UTC)
     * 完整时间戳: YYYY-MM-DD HH:00 UTC (如2015-08-01 02:00 UTC)

5. 数据来源
   - 卫星: 日本气象厅向日葵8号(Himawari-8)
   - 产品: L3级气溶胶反演产品(ARP)
   - 分辨率: 约5km (0.05°)
   - 时间分辨率: 1小时
   - 获取方式: 日本宇宙航空研究开发机构(JAXA)FTP服务器
     ftp://ftp.ptree.jaxa.jp/pub/himawari/L3/ARP/031/

6. 使用注意事项
   - 文件包含2014个特定站点的数据
   - 每个文件代表单个时间点(1小时间隔)
   - 月度数据整合后存储在H8L3ARP_monthly_YYYYMM.nc中
   - 数据通过自动化Python脚本处理，含完整日志记录
   - AOT值需结合Data_Availability标志位使用，无效值应被过滤

----------------------------------------------------------------

H8L3ARP Satellite Data File Documentation
=========================================

1. File Naming Convention
   - Format: H8L3ARP_YYYYMMDD_HH00.nc
     Example: H8L3ARP_20150801_0200.nc
   - Description:
     * YYYY: Year (4-digit)
     * MM: Month (2-digit)
     * DD: Day (2-digit)
     * HH: Hour (UTC, 2-digit)
     * 00: Minute (fixed to 00, indicating hourly data)

2. File Format
   - Format Type: NetCDF-4
   - Dimensions: 1 (Station dimension)
   - Variables: 5
   - File Size: ~150-250 KB

3. Data Content
   | Variable           | Description                             | Unit | Data Type | Dimension     |
   |--------------------|-----------------------------------------|------|-----------|---------------|
   | Station            | Station names                           | None | String    | Station(2014) |
   | Data_Availability  | Data availability flag (0:unavailable, 1:available) | None | int8      | Station(2014) |
   | Land_Water_Flag    | Land/Water flag (0:water, 1:land)       | None | int8      | Station(2014) |
   | Cloud_Flag         | Cloud flag (0:clear, 1:cloudy)          | None | int8      | Station(2014) |
   | AOT                | Aerosol optical thickness at 500 nm     | None | float32   | Station(2014) |
   | AOT_Uncertainty    | Uncertainty of aerosol optical thickness| None | float32   | Station(2014) |

4. Data Processing Notes
   - Data Extraction:
     * Extract per-station data from L3ARP product
     * Extract three bits from QA_flag_merged (data availability, land/water, cloud)
     * Extract AOT and its uncertainty at 500nm
   - Data Quality:
     * Data_Availability=0 indicates unavailable data (due to cloud, invalid values, etc.)
     * When Data_Availability=0, AOT values may be invalid (typically -9999)
     * Valid AOT range: 0.0 - 5.0 (may have outliers)
   - Time Representation:
     * Global Attribute: time = "0200" (02:00 UTC)
     * Full Timestamp: YYYY-MM-DD HH:00 UTC (e.g., 2015-08-01 02:00 UTC)

5. Data Source
   - Satellite: JMA Himawari-8
   - Product: L3 Aerosol Retrieval Product (ARP)
   - Resolution: ~5km (0.05°)
   - Temporal Resolution: 1 hour
   - Access: JAXA P-Tree FTP Server
     ftp://ftp.ptree.jaxa.jp/pub/himawari/L3/ARP/031/

6. Usage Notes
   - Contains data for 2014 specific stations
   - Each file represents a single hourly timepoint
   - Monthly data integrated in H8L3ARP_monthly_YYYYMM.nc files
   - Processed by automated Python scripts with full logging
   - AOT values should be filtered using Data_Availability flag