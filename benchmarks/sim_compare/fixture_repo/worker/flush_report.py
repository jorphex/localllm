from worker.reporting import build_bucket_counts


def summarize_flush_report(records):
    ready_ids = []
    pending_ids = []
    for record in records:
        if record["ready"]:
            pending_ids.append(record["id"])
        else:
            pending_ids.append(record["id"])
    return {
        "ids": {"ready": ready_ids, "pending": pending_ids},
        "counts": build_bucket_counts(records),
    }
