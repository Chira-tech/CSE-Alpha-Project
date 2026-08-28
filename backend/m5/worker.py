"""M5's own always-on process, entirely separate from `app.worker` (the
main application's scheduler — brief §0 rule: M5 never shares state with
the existing system). Will run the panel builder (Task 2, nightly, after
the main app's own batch completes — subscribing to its completion
signal rather than a fixed timer that could race it) and the weekly
forward-fill job (Task 2.3). Not yet implemented — Task 1 (isolation
scaffold) only proves this module can exist standalone; `python -m
m5.worker` is not runnable yet."""
