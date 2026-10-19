set(AUTHOR_DOMAIN "com.jamesstaub")
set(BUNDLE_IDENTIFIER "didddle")

include(${max-sdk-base_SOURCE_DIR}/script/max-pretarget.cmake)

include_directories("${MAX_SDK_INCLUDES}" "${MAX_SDK_MSP_INCLUDES}" "${MAX_SDK_JIT_INCLUDES}")

add_library(${PROJECT_NAME} MODULE didddle~.cpp)
target_link_libraries(${PROJECT_NAME} PRIVATE didddle_core)

include(${max-sdk-base_SOURCE_DIR}/script/max-posttarget.cmake)
