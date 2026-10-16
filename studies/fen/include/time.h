#ifndef _TIME_H
#define _TIME_H
typedef unsigned time_t;
typedef unsigned clock_t;
#define CLOCKS_PER_SEC 1000000
time_t time(time_t *t);
clock_t clock(void);
struct tm {
    int tm_sec, tm_min, tm_hour, tm_mday, tm_mon, tm_year, tm_wday, tm_yday, tm_isdst;
};
struct tm *gmtime(const time_t *t);
struct tm *localtime(const time_t *t);
char *asctime(const struct tm *tm);
char *ctime(const time_t *t);
#endif
