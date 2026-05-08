#ifndef _LWIPOPTS_H
#define _LWIPOPTS_H

/* Thread stack sizes for lwIP FreeRTOS integration */
#define TCPIP_THREAD_STACKSIZE    1024
#define DEFAULT_THREAD_STACKSIZE  2048
#define DEFAULT_RAW_RECVMBOX_SIZE 8
#define TCPIP_MBOX_SIZE           16
#define DEFAULT_UDP_RECVMBOX_SIZE TCPIP_MBOX_SIZE
#define DEFAULT_TCP_RECVMBOX_SIZE TCPIP_MBOX_SIZE
#define DEFAULT_ACCEPTMBOX_SIZE   TCPIP_MBOX_SIZE
#define LWIP_TIMEVAL_PRIVATE      0

/* Core locking for better throughput */
#define LWIP_TCPIP_CORE_LOCKING_INPUT 1

/* Mongoose requires LWIP_SOCKET=1 for socket type definitions (sockaddr etc.).
 * LWIP_COMPAT_SOCKETS=2 avoids the connect/poll/send macro definitions that are
 * guarded by "LWIP_COMPAT_SOCKETS != 2" in sockets.h — those macros break
 * pico-sdk 2.x async_context.h (.poll member) and Mongoose's OTA connect() call. */
#define LWIP_SOCKET         1
#define LWIP_COMPAT_SOCKETS 2

/* Memory */
#define MEM_LIBC_MALLOC    0
#define MEM_ALIGNMENT      4
#define MEM_SIZE           20000
#define MEMP_NUM_TCP_PCB   10
#define MEMP_NUM_TCP_SEG   32
#define MEMP_NUM_ARP_QUEUE 10
#define PBUF_POOL_SIZE     24

/* Protocol support */
#define LWIP_ARP           1
#define LWIP_ETHERNET      1
#define LWIP_ICMP          1
#define LWIP_RAW           1
#define LWIP_DHCP          1
#define LWIP_IPV4          1
#define LWIP_TCP           1
#define LWIP_UDP           1
#define LWIP_DNS           1 /* Needed for hostname resolution */
#define LWIP_TCP_KEEPALIVE 1

/* TCP tuning */
#define TCP_WND          (8 * TCP_MSS)
#define TCP_MSS          1460
#define TCP_SND_BUF      (8 * TCP_MSS)
#define TCP_SND_QUEUELEN ((4 * (TCP_SND_BUF) + (TCP_MSS - 1)) / (TCP_MSS))

/* Netif callbacks */
#define LWIP_NETIF_STATUS_CALLBACK 1
#define LWIP_NETIF_LINK_CALLBACK   1
#define LWIP_NETIF_HOSTNAME        1

/* Stats (disable to save RAM) */
#define MEM_STATS  0
#define SYS_STATS  0
#define MEMP_STATS 0
#define LINK_STATS 0

/* Misc */
#define LWIP_CHKSUM_ALGORITHM     3
#define LWIP_NETIF_TX_SINGLE_PBUF 1
#define DHCP_DOES_ARP_CHECK       0
#define LWIP_DHCP_DOES_ACD_CHECK  0

#endif /* _LWIPOPTS_H */
