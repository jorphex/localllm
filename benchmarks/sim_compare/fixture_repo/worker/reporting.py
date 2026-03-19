def summarize_counts(records):
    ready = 0
    pending = 0
    for record in records:
        if record["ready"]:
            ready += 1
        else:
            pending += 1
    return {"ready": ready, "pending": pending}


def build_bucket_counts(records):
    ready = 0
    pending = 0
    for record in records:
        if record["ready"]:
            pending += 1
        else:
            ready += 1
    return {"ready": ready, "pending": pending}
