"""A sample facts dict shaped like app.build_facts() output, for report tests."""


def sample_facts():
    return {
        "site_id": "T01", "site_name": "SAMPLE Tideflats Logistics Yard", "inspector": "J. Rivera",
        "inspection_type": "storm", "inspection_time": "Thu Nov 26, 2026 9:15 AM",
        "report_due": "Tue Dec 1, 2026 5:00 PM", "weather_notes": "Light rain, ponding near gate.",
        "rainfall": {"station": "KTIW", "distance_mi": 7.7, "max_24h_in": 0.41,
                     "trigger": "Wed Nov 25, 2026 11:00 PM", "flags": []},
        "gauge_reading": 0.38,
        "findings": [
            {"control_id": "SF-1", "title": "Silt Fence SF-1", "citation": "SWPPP §4.1", "condition": "OK",
             "notes": "", "category_label": "No action", "deadlines": [], "flags": []},
            {"control_id": "IP-2", "title": "Inlet Protection IP-2", "citation": "SWPPP §4.2",
             "condition": "Routine maintenance", "notes": "Bag half full at Inlet 3",
             "category_label": "Routine maintenance",
             "deadlines": [("Finish maintenance", "Fri Nov 27, 2026 5:00 PM", "R10"),
                           ("If infeasible (documented)", "Thu Dec 3, 2026 9:15 AM", "R10")],
             "flags": ["REPEAT_FIX_CORRECTIVE"]},
        ],
        "flags": ["CHECK_GAUGE", "REPEAT_FIX_CORRECTIVE"],
        "open_items": [
            {"deficiency_id": "D-003", "control_id": "CB-1", "description": "Insert not seated (DRAFT)",
             "deadlines": [("Complete corrective action", "Mon Nov 30, 2026 5:00 PM", "R12")], "flags": ["OVERDUE"]},
        ],
        "sections": ["1.1", "2.1", "4.1", "4.2", "4.3", "5.1"],
    }


NARRATIVE = ("A storm inspection was conducted after 0.41 in of rain.\n\n"
             "Inlet Protection IP-2 needs routine maintenance (SWPPP §4.2).")
