#!/bin/sh
set -eu
mkdir -p /backups
while true; do
  filename="/backups/workout-$(date -u +%Y%m%d-%H%M%S).dump"
  if pg_dump -h db -U workout -d workout -Fc -f "$filename"; then
    find /backups -name 'workout-*.dump' -mtime +30 -delete
    sleep 86400
  else
    rm -f "$filename"
    sleep 300
  fi
done
