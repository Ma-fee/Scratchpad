#!/bin/sh
# /etc/service/app/log/run

# 使用 svlogd 将日志输出到 /var/log/app
exec svlogd -tt /dev/stdout