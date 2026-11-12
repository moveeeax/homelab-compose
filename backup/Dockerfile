FROM restic/restic:0.19.1

# restic's base image is Alpine; add a cron daemon and bash for the loop,
# jq to read restic's JSON output and curl for the optional notify ping.
RUN apk add --no-cache dcron bash coreutils jq curl

COPY backup.sh /usr/local/bin/backup.sh
COPY restore.sh /usr/local/bin/restore.sh
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
COPY metrics.sh /usr/local/bin/metrics.sh
RUN chmod +x /usr/local/bin/backup.sh /usr/local/bin/restore.sh /usr/local/bin/entrypoint.sh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
