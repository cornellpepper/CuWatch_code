/*
 * FreeRTOS configuration for CuWatch on Raspberry Pi Pico-W / Pico2-W.
 * Adapted from the Mongoose pico-w-picosdk-freertos-lwip example.
 */
#ifndef FREERTOS_CONFIG_H
#define FREERTOS_CONFIG_H

/* Scheduler */
#define configUSE_PREEMPTION     1
#define configUSE_TICKLESS_IDLE  0
#define configUSE_IDLE_HOOK      0
#define configUSE_TICK_HOOK      0
#define configTICK_RATE_HZ       ((TickType_t)1000)
#define configMAX_PRIORITIES     32
#define configMINIMAL_STACK_SIZE ((configSTACK_DEPTH_TYPE)512)
#define configUSE_16_BIT_TICKS   0
#define configIDLE_SHOULD_YIELD  1

/* Synchronization */
#define configUSE_MUTEXES              1
#define configUSE_RECURSIVE_MUTEXES    1
#define configUSE_APPLICATION_TASK_TAG 0
#define configUSE_COUNTING_SEMAPHORES  1
#define configQUEUE_REGISTRY_SIZE      8
#define configUSE_QUEUE_SETS           1
#define configUSE_TIME_SLICING         1
#define configUSE_NEWLIB_REENTRANT     0
/* Required for lwIP FreeRTOS sys_arch */
#define configENABLE_BACKWARD_COMPATIBILITY     1
#define configNUM_THREAD_LOCAL_STORAGE_POINTERS 5

/* System */
#define configSTACK_DEPTH_TYPE           uint32_t
#define configMESSAGE_BUFFER_LENGTH_TYPE size_t

/* Memory — 128KB heap for Mongoose + lwIP + FreeRTOS overhead */
#define configSUPPORT_STATIC_ALLOCATION  0
#define configSUPPORT_DYNAMIC_ALLOCATION 1
#define configTOTAL_HEAP_SIZE            (128 * 1024)
#define configAPPLICATION_ALLOCATED_HEAP 0

/* Hook functions */
#define configCHECK_FOR_STACK_OVERFLOW     0
#define configUSE_MALLOC_FAILED_HOOK       0
#define configUSE_DAEMON_TASK_STARTUP_HOOK 0

/* Run time and task stats */
#define configGENERATE_RUN_TIME_STATS        0
#define configUSE_TRACE_FACILITY             1
#define configUSE_STATS_FORMATTING_FUNCTIONS 0

/* Co-routines */
#define configUSE_CO_ROUTINES           0
#define configMAX_CO_ROUTINE_PRIORITIES 1

/* Software timers */
#define configUSE_TIMERS             1
#define configTIMER_TASK_PRIORITY    (configMAX_PRIORITIES - 1)
#define configTIMER_QUEUE_LENGTH     10
#define configTIMER_TASK_STACK_DEPTH 1024

/* Core count — FreeRTOS runs only on Core 0.
 * Core 1 is launched bare-metal via multicore_launch_core1() for the ADC
 * detection loop.  Keeping this at 1 avoids the FreeRTOS SMP port sending
 * SIO FIFO messages to Core 1, which would deadlock with the
 * multicore_lockout_victim_init() handler that Core 1 installs for OTA. */
#define configNUMBER_OF_CORES       1
#define configUSE_PASSIVE_IDLE_HOOK 0

/* Security/MPU — not used */
#define configENABLE_MPU               0
#define configENABLE_FPU               1
#define configENABLE_TRUSTZONE         0
#define configRUN_FREERTOS_SECURE_ONLY 1

/* Cortex-M interrupt priority */
#define configMAX_SYSCALL_INTERRUPT_PRIORITY 16

/* RP2xxx pico-sdk interop */
#define configSUPPORT_PICO_SYNC_INTEROP 1
#define configSUPPORT_PICO_TIME_INTEROP 1

#include <assert.h>
#define configASSERT(x) assert(x)

/* API includes */
#define INCLUDE_vTaskPrioritySet            1
#define INCLUDE_uxTaskPriorityGet           1
#define INCLUDE_vTaskDelete                 1
#define INCLUDE_vTaskSuspend                1
#define INCLUDE_vTaskDelayUntil             1
#define INCLUDE_vTaskDelay                  1
#define INCLUDE_xTaskGetSchedulerState      1
#define INCLUDE_xTaskGetCurrentTaskHandle   1
#define INCLUDE_uxTaskGetStackHighWaterMark 1
#define INCLUDE_xTaskGetIdleTaskHandle      1
#define INCLUDE_eTaskGetState               1
#define INCLUDE_xTimerPendFunctionCall      1
#define INCLUDE_xTaskAbortDelay             1
#define INCLUDE_xTaskGetHandle              1
#define INCLUDE_xTaskResumeFromISR          1
#define INCLUDE_xQueueGetMutexHolder        1

#endif /* FREERTOS_CONFIG_H */
