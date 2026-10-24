    # If the week is already marked as a school closure / holiday in the parent
    # calendar, do not create a "No TimeTBL" entry. "No TimeTBL" is reserved for
    # the case where the timetable feed itself is unavailable (e.g. switched off),
    # not for normal school holidays.
    no_school_events = gcal_list_tagged_events(
        service, parent_cal_id, TAG_NO_SCHOOL, "true", week_start, week_end
    )
    if no_school_events:
        existing_no_timetable = gcal_list_tagged_events(
            service, parent_cal_id, TAG_NO_TIMETABLE, "true", week_start, week_end
        )
        for ev in existing_no_timetable:
            gcal_delete_event(service, parent_cal_id, ev["id"], dry_run)
        if existing_no_timetable:
            print(f"  Removed {len(existing_no_timetable)} stale 'No TimeTBL' marker(s) because 'No School' is active")
        print(f"  'No School' marker(s) found for {week_from}–{week_to} — skipping 'No TimeTBL'")
        return

    # If the timetable is missing because it's unavailable (switched off), create
    # a No TimeTBL marker. Otherwise, we are in a normal school holiday/weekend
    # closure and No School is the correct marker.
