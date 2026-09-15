# Unattended soak protocol

This profile is a disposable acceptance run. Complete each goal ONLY with the
tools the goal names (`HostOSWriter.write_file` / `HostOSReader.read_file`).

Never call `GoalSkills.update_goal`, `GoalSkills.set_current_goal` or
`GoalSkills.execute_skill` in this profile: the acceptance harness records
those as protocol violations and the run fails. Do not delegate, do not create
sub-goals, do not narrate progress; perform the write and stop.
