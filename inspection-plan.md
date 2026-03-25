巡检命令
df -Th	#存储情况、录像存储空间
free -m	#内存
cat /proc/cpuinfo	#CPU数量
top	            #CPU负载情况、僵尸进程
ps -A -ostat,ppid,pid,cmd |grep -e '^[Zz]'	#定位僵尸进程
uptime	#服务器负载均衡
top -p $dockerPID	#docker进程内存占用（单位为KB）
jmsctl status	  #节点组件状态
jmsctl version    #版本信息

进库
grep -r "DB_" /opt/jumpserver/config/config.txt

use information_schema;
select table_name,table_rows from tables where table_schema='jumpserver' order by table_rows desc limit 10;	   #数据量最多的表


ps -aux --sort=-%mem|head -n 11             #列出系统中占用内存最高的前 10 个进程
find / -type f -size +1G  -print0 | xargs -0 du -h | sort -n   #查找占用磁盘空间较大的文件

# 根据系统类型，查看防火墙开放策略
firewall-cmd --list-all                     #centos系统
ufw status                                  #ubuntu系统