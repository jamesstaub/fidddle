Max SDK sources are not committed. `max/CMakeLists.txt` uses `third_party/max-sdk-base` if present and
otherwise fetches it from https://github.com/Cycling74/max-sdk-base at configure time. To vendor it:

    git clone --depth 1 https://github.com/Cycling74/max-sdk-base.git third_party/max-sdk-base
