# TODO

- The Rerun viewer (`scripts/run_rerun_stack.sh`) replays the recorder truth stream; live JSON UDP telemetry and the pilot shim are retired.
- Still open: decide whether `scripts/render_showcase_movie.py` gets a capture path on the Rerun viewer or is retired along with its old RViz capture inputs.
- Still open: ask the `pysos_sysml` owner to make `controlPort` optional so the entity manifest can drop the vestigial control endpoint and `PYSOS_CONTROL_PORT`.
