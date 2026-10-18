#pragma once

namespace amr {

void driveBegin();
void driveSet(int left, int right);
void driveCoast();
void driveNoteHeartbeat();

// When a non-zero drive command is active and the heartbeat window expires,
// coasts the motors and returns true once.
bool drivePollTimeout();

}  // namespace amr
