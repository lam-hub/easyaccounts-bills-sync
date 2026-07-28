# EasyAccounts Bills Sync

微信/支付宝账单自动同步到 EasyAccounts 记账系统。

## 功能特性

- **邮件监听**：自动检测并下载微信/支付宝账单邮件附件
- **账单解析**：支持微信 XLSX 和支付宝 CSV 格式
- **数据导入**：调用 EasyAccounts API 写入本地记账系统
- **辅助工具**：数据修复、退款标记

## 工作流程

```
邮件监听 → 下载账单附件 → 解压 → 解析CSV/XLSX → 调用API导入
```

1. 监听邮箱，检测微信/支付宝发送的账单邮件
2. 下载邮件中的 ZIP 附件（含密码）
3. 解压并解析账单文件（微信 XLSX / 支付宝 CSV）
4. 通过 EasyAccounts API 将账单数据写入数据库
5. 记录已处理文件，避免重复导入

## 文件结构

```
├── main.py                    # 主程序入口
├── email_listener.py          # 邮件监听模块
├── csv_parser.py              # 账单解析模块
├── easyaccounts_import.py     # EasyAccounts API 集成
├── easyaccounts_fix.py        # 数据修复工具
├── easyaccounts_mark_refund.py # 退款标记工具
├── config.yaml                # 配置文件
└── data/                      # 下载的账单文件（自动生成）
```

## 配置说明

编辑 `config.yaml`：

```yaml
email:
  host: imap.qq.com
  port: 993
  user: your_email@qq.com
  password: your_app_password

easyaccounts:
  base_url: http://localhost:10669
  token: your_api_token

wechat:
  zip_password: 微信支付公众号查看

alipay:
  zip_password: 支付宝账单密码
```

## 使用方法

### 手动执行

```bash
# 同步所有账单
python main.py

# 仅处理微信账单
python main.py --platform wechat

# 仅处理支付宝账单
python main.py --platform alipay

# 指定账单文件
python main.py --file /path/to/bill.zip
```

### 辅助工具

```bash
# 修复数据（重新导入失败的记录）
python easyaccounts_fix.py

# 标记退款记录
python easyaccounts_mark_refund.py
```

## 依赖

```bash
pip install pyyaml openpyxl requests
```

## 注意事项

- 微信账单 ZIP 密码需在微信支付公众号查看
- 支付宝账单 CSV 需要设置导出密码
- 建议使用专用邮箱接收账单，避免误删
- 首次运行会创建默认账户和分类数据

## 相关项目

- [EasyAccounts](https://github.com/775495797/EasyAccounts) - 本地记账系统
- [Bills-save](https://github.com/edge-sky/Bills-save) - 原项目（Notion 版本）

## License

MIT
