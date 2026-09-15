#!/usr/bin/env bash
# Channel status for THIS session's target mac: the one its live ssh login's key names, else the only
# online mac, else the `rexec --use` default.
# First line: ONLINE / OFFLINE / AMBIGUOUS / NOT_INSTALLED, then the mac table.
[ -x /var/lib/rexec/bin/rexec ] || { echo NOT_INSTALLED; exit 0; }
. /var/lib/rexec/bin/rexec-lib.sh
NOW=$(date +%s)
LOGIN=$(session_mac)
USE=$(default_mac)
TARGET=$(resolve_mac 2>/dev/null); RC=$?
if   [ "$RC" = 3 ];              then STATE=AMBIGUOUS; TARGET=""
elif [ "$TARGET" = "__none__" ]; then STATE=OFFLINE;   TARGET=""
elif mac_online "$TARGET";       then STATE=ONLINE
else                                  STATE=OFFLINE; fi
echo "$STATE"
printf '  session login key: %s\n' "${LOGIN:-none (not a live ssh login)}"
printf '  rexec --use default: %s\n' "${USE:-none}"
FOUND=0
for m in $(all_macs); do
  FOUND=1; hb=$(mac_hb "$m")
  if mac_online "$m"; then s="ONLINE   (heartbeat $(( NOW - hb ))s ago)"
  elif [ "$hb" = 0 ];  then s="OFFLINE  (never sent a heartbeat)"
  else                      s="OFFLINE  (heartbeat stopped $(( NOW - hb ))s ago)"; fi
  d='  '; [ "$m" = "$TARGET" ] && d='->'
  printf '  %s %-18s %s  %s\n' "$d" "$m" "$s" "$(mac_label "$m")"
done
[ "$FOUND" = 0 ] && echo "  (no mac has registered yet)"
case "$STATE" in
  ONLINE)    echo "  -> this session's mac; jobs go there";;
  OFFLINE)
    if [ -n "$LOGIN" ]; then
      echo "  the agent on this session's mac ($LOGIN) is not running - start it there, and do not use another mac"
    else
      echo "  no agent is online - ask the user to start one on the mac they are using"
    fi;;
  AMBIGUOUS) echo "  several macs online and none chosen - ask the user which one, then rexec --use <name>";;
esac
exit 0
