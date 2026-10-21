// Release version, set by CMake from the VERSION file at the repository root (semantic versioning).
#pragma once
#ifndef FIDDDLE_VERSION
#define FIDDDLE_VERSION "unknown"
#endif
namespace fidddle {
inline const char* version() { return FIDDDLE_VERSION; }
}  // namespace fidddle
