# 巡检命令清单

## 系统基础巡检

- `df -Th`
  - 存储情况、录像存储空间
- `free -m`
  - 内存使用情况
- `cat /proc/cpuinfo`
  - CPU 数量与基础信息
- `top`
  - CPU 负载情况、僵尸进程线索
- `ps -A -ostat,ppid,pid,cmd | grep -e '^[Zz]'`
  - 定位僵尸进程
- `uptime`
  - 服务器负载均衡情况
- `top -p $dockerPID`
  - Docker 进程内存占用，单位为 KB
- `jmsctl status`
  - 节点组件状态
- `jmsctl version`
  - 版本信息

## 数据库配置与容量检查

- `grep -r "DB_" /opt/jumpserver/config/config.txt`
  - 读取数据库连接配置

```sql
use information_schema;
select table_name, table_rows
from tables
where table_schema = 'jumpserver'
order by table_rows desc
limit 10;
```

- 用于查看数据量最多的表

## 容量与安全补充检查

- `ps -aux --sort=-%mem | head -n 11`
  - 列出系统中占用内存最高的前 10 个进程
- `find / -type f -size +1G -print0 | xargs -0 du -h | sort -n`
  - 查找占用磁盘空间较大的文件
- `firewall-cmd --list-all`
  - CentOS 系统防火墙策略
- `ufw status`
  - Ubuntu 系统防火墙策略
