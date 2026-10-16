/* Time: the clock on the I/O card read once by the kernel at boot, and the
 * timer's ticks since. */

#include <stdio.h>
#include <time.h>
#include <unistd.h>
#include <fen/sys.h>

time_t time(time_t *t)
{
    time_t now = sysinfo(SI_EPOCH) + sysinfo(SI_TICKS) / 100;
    if (t)
        *t = now;
    return now;
}

clock_t clock(void)
{
    return time_us();
}

unsigned sleep(unsigned s)
{
    while (s > 4000) {
        sleep_us(4000000000u);
        s -= 4000;
    }
    sleep_us(s * 1000000u);
    return 0;
}

int usleep(unsigned us)
{
    sleep_us(us);
    return 0;
}

static int leap(int y)
{
    return (y % 4 == 0 && y % 100 != 0) || y % 400 == 0;
}

struct tm *gmtime(const time_t *t)
{
    static struct tm tm;
    static const int mdays[12] = {31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
    unsigned s = *t, days = s / 86400;
    int y = 1970, m = 0;
    tm.tm_sec = s % 60;
    tm.tm_min = s / 60 % 60;
    tm.tm_hour = s / 3600 % 24;
    tm.tm_wday = (days + 4) % 7;
    while (days >= (unsigned)(leap(y) ? 366 : 365)) {
        days -= leap(y) ? 366 : 365;
        y++;
    }
    tm.tm_yday = days;
    for (;;) {
        int n = mdays[m] + (m == 1 && leap(y));
        if (days < (unsigned)n)
            break;
        days -= n;
        m++;
    }
    tm.tm_year = y - 1900;
    tm.tm_mon = m;
    tm.tm_mday = days + 1;
    tm.tm_isdst = 0;
    return &tm;
}

struct tm *localtime(const time_t *t)
{
    return gmtime(t);
}

char *asctime(const struct tm *tm)
{
    static char buf[32];
    static const char days[] = "SunMonTueWedThuFriSat";
    static const char months[] = "JanFebMarAprMayJunJulAugSepOctNovDec";
    snprintf(buf, sizeof buf, "%.3s %.3s %2d %02d:%02d:%02d %d\n", days + 3 * tm->tm_wday,
             months + 3 * tm->tm_mon, tm->tm_mday, tm->tm_hour, tm->tm_min, tm->tm_sec,
             1900 + tm->tm_year);
    return buf;
}

char *ctime(const time_t *t)
{
    return asctime(localtime(t));
}
