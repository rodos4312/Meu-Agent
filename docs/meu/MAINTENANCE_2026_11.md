# November maintenance

These changes are on `dev/meu-foundation`, after the published dev.22 release.
No new desktop distribution is requested by this maintenance batch.

## Checkpointed background projects

`coordinate_project` now uses native asynchronous delegation for interactive
sessions. It keeps the saved project locked until the native batch settles,
while allowing read-only live status. Each helper saves its result before
joining its sibling. Results also remain in the native async ledger; a project
checkpoint does not replace the native receipt.

The originating conversation receives the native completion. An ordinary turn
interrupt leaves detached work running; explicit session/helper stop still
reaches the children. Finite sessions retain synchronous execution. No additional
model call, provider switch, automatic acceptance, permission prompt or memory
approval policy is introduced.

A new-process rehearsal runs real native agents against scripted model responses
and real project files, terminates the process after one parallel helper finishes,
then resumes in another process. Finished work is retained for review; unfinished
work is marked interrupted and is not replayed automatically. External model
services are not called by these tests.

Local validation passed 192 distinct tests across the coordinator and affected
native delegation suites. Two tests belonging to other operating systems were
skipped on Windows. The new background behavior also fails against the previous
synchronous project implementation. Python lint and the code-health ratchet pass.

## Windows application registration

An existing dev.22 installation had a dev.22 executable and uninstaller but an old
dev.16 `DisplayVersion` in its matching per-user uninstall entry. Its previous
value was recorded and that one version label was corrected. The application and
profile were not replaced. The historical cause has not been established.

The real Windows installer smoke test now checks that the matching uninstall
entry and installed executable report the same version. The native upgrade and
automatic rollback rehearsals check the corresponding target/restored version
and record `windowsRegistrationVerified` in their evidence. This is a read-only
test contract, not a new application-startup registry repair mechanism.

The clean install/repair/uninstall/reinstall rehearsal passed on GitHub Windows
in [run 42039627692](https://github.com/rodos4312/Meu-Agent/actions/runs/42039627692).
The same registration mismatch did not reproduce on that clean runner.
