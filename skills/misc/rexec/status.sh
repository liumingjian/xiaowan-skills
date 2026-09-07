#!/usr/bin/env bash
# Channel status for THIS session's mac - the one it ssh'd in from, resolved by source IP.
# First line: ONLINE / OFFLINE / AMBIGUOUS / NOT_INSTALLED, then the mac table.
[ -x /var/lib/rexec/bin/rexec ] || { echo NOT_INSTALLED; exit 0; }
. /var/lib/rexec/bin/rexec-lib.sh
NOW=$(date +%s)
IP=$(origin_ip)
TARGET=$(resolve_mac 2>/dev/null); RC=$?
if   [ "$RC" = 3 ];              then STATE=AMBIGUOUS; TARGET=""
elif [ "$TARGET" = "__none__" ]; then STATE=OFFLINE;   TARGET=""
elif mac_online "$TARGET";       then STATE=ONLINE
else                                  STATE=OFFLINE; fi
echo "$STATE"
printf '  session origin: %s\n' "${IP:-unknown (not an ssh session)}"
FOUND=0
for m in $(all_macs); do
  FOUND=1; hb=$(mac_hb "$m")
  if mac_online "$m"; then s="ONLINE   (heartbeat $(( NOW - hb ))s ago)"
  elif [ "$hb" = 0 ];  then s="OFFLINE  (never sent a heartbeat)"
  else                      s="OFFLINE  (heartbeat stopped $(( NOW - hb ))s ago)"; fi
  d='  '; [ "$m" = "$TARGET" ] && d='->'
  printf '  %s %-18s %-16s %s  %s\n' "$d" "$m" \
    "$(cat "$MACS/$m/origin" 2>/dev/null || echo -)" "$s" "$(mac_label "$m")"
done
[ "$FOUND" = 0 ] && echo "  (no mac has registered yet)"
case "$STATE" in
  ONLINE)    echo "  -> this session's mac; jobs go there";;
  OFFLINE)   echo "  no agent is running on this session's mac - start it there, and do not use another mac";;
  AMBIGUOUS) echo "  several macs share this source IP - ask the user which one, then pass --mac <name>";;
esac
exit 0
