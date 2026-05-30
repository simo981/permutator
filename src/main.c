#define _DARWIN_C_SOURCE
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <fcntl.h>
#include <getopt.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

typedef struct bool_t
{
  uint8_t leet_vowel : 1;
  uint8_t leet_full : 1;
  uint8_t upper_first : 1;
  uint8_t upper_full : 1;
  uint8_t only_transform : 1;
  uint8_t reverse_words : 1;
  uint8_t reverse_full : 1;
  uint8_t charset : 1;
  uint8_t memory : 1;
} modifiers_t;

static int x_posix_fallocate(int fd, off_t offset, off_t len)
{
#if defined(__APPLE__)
    fstore_t store = {
        .fst_flags = F_ALLOCATECONTIG,
        .fst_posmode = F_PEOFPOSMODE,
        .fst_offset = offset,
        .fst_length = len,
        .fst_bytesalloc = 0,
    };

    if (fcntl(fd, F_PREALLOCATE, &store) < 0) {
        store.fst_flags = F_ALLOCATEALL;
        if (fcntl(fd, F_PREALLOCATE, &store) < 0) {
            return errno;
        }
    }

    if (ftruncate(fd, offset + len) < 0) {
        return errno;
    }

    return 0;
#else
    return posix_fallocate(fd, offset, len);
#endif
}

#ifndef BUFF
#define BUFF 1024
#endif

#ifndef OUT_BUFSZ
#define OUT_BUFSZ (64 * 1024 * 1024)
#endif

#ifndef OUT_DONTNEED_STEP
#define OUT_DONTNEED_STEP (64 * 1024 * 1024)
#endif

#ifndef OUT_PREALLOC_SIZE
#define OUT_PREALLOC_SIZE (2LL * OUT_DONTNEED_STEP)
#endif

typedef struct {
    char *s;
    size_t len;
    bool one;
    bool pal_multi;
} Item;

typedef struct {
    char *raw;
    size_t raw_len;
    bool raw_one;
    bool raw_pal_multi;
    bool has_comma;
    char *p1;
    size_t p1_len;
    bool p1_one;
    bool p1_pal_multi;
    char *p2;
    size_t p2_len;
    bool p2_one;
    bool p2_pal_multi;
} Word;

typedef struct {
    int fd;
    char *buf;
    size_t len;
    size_t cap;
    off_t written;
    off_t advised;
    bool truncate_on_close;
} Out;

typedef struct {
    Out *out;
    bool can_reverse;
    char lastbuf[BUFF];
    char leetbuf[BUFF];
    char upperbuf[BUFF];
    char revbuf[BUFF];
} Gen;

static size_t max_len = 0;
static size_t min_len = 0;
static size_t word_size = 0;
static Word *words = NULL;
static const char *connector_chars = NULL;
static size_t connectors_size = 0;
static char **last = NULL;
static size_t *last_len = NULL;
static size_t last_size = 0;
static unsigned char leet_map[256];
static modifiers_t bool_modifiers;
static bool opt_has_upper = false;
static bool opt_has_leet = false;
static bool opt_has_reverse = false;
static bool opt_has_mutating = false;
static bool opt_has_last = false;
static bool opt_has_connectors = false;
static bool opt_repeat = false;

static void die(const char *s)
{
    perror(s);
    exit(1);
}

static void diex(const char *s)
{
    fputs(s, stderr);
    fputc('\n', stderr);
    exit(1);
}

static void *xmalloc(size_t n)
{
    void *p = malloc(n ? n : 1);
    if (!p) {
        die("malloc");
    }
    return p;
}

static char *xstrndup2(const char *s, size_t n)
{
    char *p = xmalloc(n + 1);
    memcpy(p, s, n);
    p[n] = '\0';
    return p;
}

static uint64_t parse_u64(const char *s, const char *err)
{
    char *end = NULL;
    errno = 0;
    unsigned long long v = strtoull(s, &end, 10);
    if (errno || !s[0] || *end) {
        diex(err);
    }
    return (uint64_t)v;
}


static inline bool palindrome_raw(const char *s, size_t n)
{
    if (n < 2) {
        return true;
    }
    const char *a = s;
    const char *b = s + n - 1;
    while (a < b) {
        if (*a++ != *b--) {
            return false;
        }
    }
    return true;
}

static inline bool pal_multi(const char *s, size_t n)
{
    return n > 1 && palindrome_raw(s, n);
}

static inline void word_raw_item(const Word *w, Item *it)
{
    it->s = w->raw;
    it->len = w->raw_len;
    it->one = w->raw_one;
    it->pal_multi = w->raw_pal_multi;
}

static inline void word_p1_item(const Word *w, Item *it)
{
    it->s = w->p1;
    it->len = w->p1_len;
    it->one = w->p1_one;
    it->pal_multi = w->p1_pal_multi;
}

static inline void word_p2_item(const Word *w, Item *it)
{
    it->s = w->p2;
    it->len = w->p2_len;
    it->one = w->p2_one;
    it->pal_multi = w->p2_pal_multi;
}

static void write_all(int fd, const void *buf, size_t n)
{
    const char *p = buf;
    while (n) {
        ssize_t w = write(fd, p, n);
        if (w < 0) {
            if (errno == EINTR) {
                continue;
            }
            die("write");
        }
        if (w == 0) {
            diex("write returned 0");
        }
        p += (size_t)w;
        n -= (size_t)w;
    }
}

static void out_advise_written(Out *o)
{
#if defined(POSIX_FADV_DONTNEED) && OUT_DONTNEED_STEP > 0
    if (o->written - o->advised >= (off_t)OUT_DONTNEED_STEP) {
        (void)posix_fadvise(o->fd, o->advised, o->written - o->advised, POSIX_FADV_DONTNEED);
        o->advised = o->written;
    }
#else
    (void)o;
#endif
}

static void out_flush(Out *o)
{
    if (!o->len) {
        return;
    }
    write_all(o->fd, o->buf, o->len);
    o->written += (off_t)o->len;
    o->len = 0;
    out_advise_written(o);
}

static inline void out_write(Out *o, const void *buf, size_t n)
{
    if (!n) {
        return;
    }
    if (n > o->cap) {
        out_flush(o);
        write_all(o->fd, buf, n);
        o->written += (off_t)n;
        out_advise_written(o);
        return;
    }
    if (o->len + n > o->cap) {
        out_flush(o);
    }
    memcpy(o->buf + o->len, buf, n);
    o->len += n;
}

static inline void out_char(Out *o, char c)
{
    if (o->len == o->cap) {
        out_flush(o);
    }
    o->buf[o->len++] = c;
}

static inline void out_line(Out *o, const char *s, size_t n)
{
    if (n + 1 > o->cap) {
        out_flush(o);
        write_all(o->fd, s, n);
        write_all(o->fd, "\n", 1);
        o->written += (off_t)n + 1;
        out_advise_written(o);
        return;
    }
    if (o->len + n + 1 > o->cap) {
        out_flush(o);
    }
    memcpy(o->buf + o->len, s, n);
    o->len += n;
    o->buf[o->len++] = '\n';
}

static inline void out_line_base_last(Out *o, const char *base, size_t n, const char *suf, size_t sn)
{
    out_write(o, base, n);
    out_write(o, suf, sn);
    out_char(o, '\n');
}

static inline void out_line_connector(Out *o, const char *base, size_t pos, size_t n, char c)
{
    out_write(o, base, pos);
    out_char(o, c);
    out_write(o, base + pos, n - pos);
    out_char(o, '\n');
}

static inline void out_line_connector_last(
    Out *o,
    const char *base,
    size_t pos,
    size_t n,
    char c,
    const char *suf,
    size_t sn
)
{
    out_write(o, base, pos);
    out_char(o, c);
    out_write(o, base + pos, n - pos);
    out_write(o, suf, sn);
    out_char(o, '\n');
}

static void out_open(Out *o, const char *path, char *buf, size_t cap, off_t reserve)
{
    bool null_output = !strcmp(path, "-");
    o->fd = open(null_output ? "/dev/null" : path, null_output ? O_WRONLY : (O_RDWR | O_CREAT | O_TRUNC), 0644);
    if (o->fd < 0) {
        die("open");
    }
    o->truncate_on_close = !null_output;
#if defined(POSIX_FADV_SEQUENTIAL)
    (void)posix_fadvise(o->fd, 0, 0, POSIX_FADV_SEQUENTIAL);
#endif
    if (!null_output && reserve > 0) {
        int e = x_posix_fallocate(o->fd, 0, reserve);
        if (e) {
            errno = e;
            die("x_posix_fallocate");
        }
    }
    o->buf = buf;
    o->cap = cap;
    o->len = 0;
    o->written = 0;
    o->advised = 0;
}

static void out_close(Out *o)
{
    out_flush(o);
    if (o->truncate_on_close && ftruncate(o->fd, o->written) < 0) {
        die("ftruncate");
    }
    if (close(o->fd) < 0) {
        die("close");
    }
    o->fd = -1;
}

static inline void reverse_copy(char *restrict dst, const char *restrict src, size_t n)
{
    for (size_t i = 0; i < n; i++) {
        dst[i] = src[n - 1 - i];
    }
    dst[n] = '\0';
}

static inline bool leet_encode(char *s, size_t n)
{
    bool changed = false;
    for (size_t i = 0; i < n; i++) {
        unsigned char c = leet_map[(unsigned char)s[i]];
        changed |= c != 0;
        s[i] = c ? (char)c : s[i];
    }
    return changed;
}

static inline bool upper_encode(char *s, size_t n)
{
    bool changed = false;
    if (bool_modifiers.upper_full) {
        for (size_t i = 0; i < n; i++) {
            unsigned char c = (unsigned char)s[i];
            bool lower = c >= (unsigned char)'a' && c <= (unsigned char)'z';
            changed |= lower;
            s[i] = lower ? (char)(c - ((unsigned char)'a' - (unsigned char)'A')) : s[i];
        }
    } else if (n > 0) {
        unsigned char c = (unsigned char)s[0];
        bool lower = c >= (unsigned char)'a' && c <= (unsigned char)'z';
        changed = lower;
        if (lower) {
            s[0] = (char)(c - ((unsigned char)'a' - (unsigned char)'A'));
        }
    }
    return changed;
}

static inline void emit_final(Gen *g, const char *s, size_t n, bool changed)
{
    if (!bool_modifiers.only_transform || changed) {
        out_line(g->out, s, n);
    }
}

static void stage_reverse_full(Gen *g, char *s, size_t n, bool changed)
{
    emit_final(g, s, n, changed);
    if (g->can_reverse && bool_modifiers.reverse_full) {
        reverse_copy(g->revbuf, s, n);
        emit_final(g, g->revbuf, n, true);
    }
}

static void stage_upper(Gen *g, char *s, size_t n, bool changed)
{
    stage_reverse_full(g, s, n, changed);
    if (opt_has_upper) {
        memcpy(g->upperbuf, s, n + 1);
        if (upper_encode(g->upperbuf, n)) {
            stage_reverse_full(g, g->upperbuf, n, true);
        }
    }
}

static void stage_leet(Gen *g, char *s, size_t n, bool changed)
{
    stage_upper(g, s, n, changed);
    if (opt_has_leet) {
        memcpy(g->leetbuf, s, n + 1);
        if (leet_encode(g->leetbuf, n)) {
            stage_upper(g, g->leetbuf, n, true);
        }
    }
}

static void stage_last(Gen *g, char *s, size_t n, bool changed)
{
    stage_leet(g, s, n, changed);
    if (!opt_has_last) {
        return;
    }
    for (size_t i = 0; i < last_size; i++) {
        size_t ln = last_len[i];
        if (n + ln >= BUFF) {
            diex("BUFF too small");
        }
        memcpy(g->lastbuf, s, n);
        memcpy(g->lastbuf + n, last[i], ln);
        g->lastbuf[n + ln] = '\0';
        stage_leet(g, g->lastbuf, n + ln, true);
    }
}

static void print_out_plain(Out *out, Item *arr, size_t size)
{
    char base[BUFF];
    size_t offsets[size];
    size_t run_len = 0;
    const bool need_offsets = opt_has_connectors && size >= 2;
    for (size_t i = 0; i < size; i++) {
        size_t n = arr[i].len;
        if (run_len + n >= BUFF) {
            diex("BUFF too small");
        }
        memcpy(base + run_len, arr[i].s, n);
        run_len += n;
        if (need_offsets) {
            offsets[i] = run_len;
        }
    }
    base[run_len] = '\0';
    if (!bool_modifiers.only_transform) {
        out_line(out, base, run_len);
    }
    if (opt_has_last) {
        for (size_t i = 0; i < last_size; i++) {
            out_line_base_last(out, base, run_len, last[i], last_len[i]);
        }
    }
    if (!need_offsets) {
        return;
    }
    for (size_t i = 0; i < size - 1; i++) {
        size_t pos = offsets[i];
        for (size_t y = 0; y < connectors_size; y++) {
            char c = connector_chars[y];
            out_line_connector(out, base, pos, run_len, c);
            if (opt_has_last) {
                for (size_t j = 0; j < last_size; j++) {
                    out_line_connector_last(out, base, pos, run_len, c, last[j], last_len[j]);
                }
            }
        }
    }
}

static void print_out_transform(Out *out, Item *arr, size_t size)
{
    char base[BUFF];
    size_t offsets[size];
    size_t run_len = 0;
    size_t one = 0;
    size_t pal = 0;
    const bool need_offsets = opt_has_connectors && size >= 2;
    for (size_t i = 0; i < size; i++) {
        size_t n = arr[i].len;
        if (run_len + n >= BUFF) {
            diex("BUFF too small");
        }
        memcpy(base + run_len, arr[i].s, n);
        run_len += n;
        if (need_offsets) {
            offsets[i] = run_len;
        }
        if (opt_has_reverse) {
            one += arr[i].one;
            pal += arr[i].pal_multi;
        }
    }
    base[run_len] = '\0';
    Gen g = {
        .out = out,
        .can_reverse = opt_has_reverse && (one != size && pal != size)
    };
    stage_last(&g, base, run_len, false);
    if (g.can_reverse && bool_modifiers.reverse_words) {
        char seed[BUFF];
        reverse_copy(seed, base, run_len);
        stage_last(&g, seed, run_len, true);
    }
    if (!need_offsets) {
        return;
    }
    if (run_len + 1 >= BUFF) {
        diex("BUFF too small");
    }
    char seed[BUFF];
    for (size_t i = 0; i < size - 1; i++) {
        size_t pos = offsets[i];
        memcpy(seed, base, pos);
        memcpy(seed + pos + 1, base + pos, run_len - pos);
        seed[run_len + 1] = '\0';
        for (size_t y = 0; y < connectors_size; y++) {
            seed[pos] = connector_chars[y];
            stage_last(&g, seed, run_len + 1, true);
        }
    }
}

static inline void print_out(Out *out, Item *arr, size_t size)
{
    if (!size) {
        return;
    }
    if (opt_has_mutating) {
        print_out_transform(out, arr, size);
    } else {
        print_out_plain(out, arr, size);
    }
}

static inline void swap_item(Item *a, Item *b)
{
    Item t = *a;
    *a = *b;
    *b = t;
}

static void permute_emit(Out *out, Item *arr, size_t n)
{
    Item work[n];
    memcpy(work, arr, sizeof(*work) * n);
    print_out(out, work, n);
    if (n < 2) {
        return;
    }
    size_t p[n];
    memset(p, 0, sizeof p);
    size_t i = 1;
    while (i < n) {
        if (p[i] < i) {
            size_t j = (i & 1) ? p[i] : 0;
            swap_item(&work[i], &work[j]);
            print_out(out, work, n);
            p[i]++;
            i = 1;
        } else {
            p[i++] = 0;
        }
    }
}

static void expand_comma_variants(Out *out, Word **selected, size_t idx, size_t n, Item *items)
{
    if (idx == n) {
        permute_emit(out, items, n);
        return;
    }
    Word *w = selected[idx];
    if (!w->has_comma) {
        word_raw_item(w, &items[idx]);
        expand_comma_variants(out, selected, idx + 1, n, items);
        return;
    }
    word_p1_item(w, &items[idx]);
    expand_comma_variants(out, selected, idx + 1, n, items);
    word_p2_item(w, &items[idx]);
    expand_comma_variants(out, selected, idx + 1, n, items);
}

static void expand_comma_variants_ordered(Out *out, Word **selected, size_t idx, size_t n, Item *items)
{
    if (idx == n) {
        print_out(out, items, n);
        return;
    }
    Word *w = selected[idx];
    if (!w->has_comma) {
        word_raw_item(w, &items[idx]);
        expand_comma_variants_ordered(out, selected, idx + 1, n, items);
        return;
    }
    word_p1_item(w, &items[idx]);
    expand_comma_variants_ordered(out, selected, idx + 1, n, items);
    word_p2_item(w, &items[idx]);
    expand_comma_variants_ordered(out, selected, idx + 1, n, items);
}

static void emit_selected(Out *out, Word **selected, size_t n)
{
    Item items[n];
    expand_comma_variants(out, selected, 0, n, items);
}

static void emit_selected_ordered(Out *out, Word **selected, size_t n)
{
    Item items[n];
    expand_comma_variants_ordered(out, selected, 0, n, items);
}

static void gen_subsets(Out *out, size_t idx, size_t cur, Word **selected)
{
    if (cur > max_len) {
        return;
    }
    size_t remaining = word_size - idx;
    if (cur + remaining < min_len) {
        return;
    }
    if (idx == word_size) {
        if (cur >= min_len && cur <= max_len) {
            emit_selected(out, selected, cur);
        }
        return;
    }
    gen_subsets(out, idx + 1, cur, selected);
    if (cur < max_len) {
        selected[cur] = &words[idx];
        gen_subsets(out, idx + 1, cur + 1, selected);
    }
}

static void gen_repeats_exact(Out *out, size_t target, size_t pos, Word **selected)
{
    if (pos == target) {
        emit_selected_ordered(out, selected, target);
        return;
    }
    for (size_t i = 0; i < word_size; i++) {
        selected[pos] = &words[i];
        gen_repeats_exact(out, target, pos + 1, selected);
    }
}

static void gen_repeats(Out *out, Word **selected)
{
    for (size_t n = min_len; n <= max_len; n++) {
        gen_repeats_exact(out, n, 0, selected);
    }
}

static void parse_last(char *arg)
{
    size_t n = 1;
    for (char *p = arg; *p; p++) {
        if (*p == ',') {
            n++;
        }
    }
    last = xmalloc(sizeof(*last) * n);
    last_len = xmalloc(sizeof(*last_len) * n);
    char *tok = strtok(arg, ",");
    size_t i = 0;
    while (tok) {
        last[i] = tok;
        last_len[i] = strlen(tok);
        i++;
        tok = strtok(NULL, ",");
    }
    last_size = i;
}

static void init_modes(void)
{
    opt_has_upper = bool_modifiers.upper_first || bool_modifiers.upper_full;
    opt_has_leet = bool_modifiers.leet_full || bool_modifiers.leet_vowel;
    opt_has_reverse = bool_modifiers.reverse_words || bool_modifiers.reverse_full;
    opt_has_last = last != NULL && last_size != 0;
    opt_has_connectors = connector_chars != NULL && connectors_size != 0;
    opt_has_mutating = opt_has_upper || opt_has_leet || opt_has_reverse;
}

static void init_leet(void)
{
    memset(leet_map, 0, sizeof leet_map);
    leet_map[(unsigned char)'a'] = '4';
    leet_map[(unsigned char)'A'] = '4';
    leet_map[(unsigned char)'e'] = '3';
    leet_map[(unsigned char)'E'] = '3';
    leet_map[(unsigned char)'i'] = '1';
    leet_map[(unsigned char)'I'] = '1';
    leet_map[(unsigned char)'o'] = '0';
    leet_map[(unsigned char)'O'] = '0';
    if (bool_modifiers.leet_full) {
        leet_map[(unsigned char)'s'] = '5';
        leet_map[(unsigned char)'S'] = '5';
        leet_map[(unsigned char)'t'] = '7';
        leet_map[(unsigned char)'T'] = '7';
        leet_map[(unsigned char)'g'] = '9';
        leet_map[(unsigned char)'G'] = '9';
        leet_map[(unsigned char)'z'] = '2';
        leet_map[(unsigned char)'Z'] = '2';
    }
}

static void parse_words(char **argv, int first_word_idx, int argc)
{
    word_size = (size_t)(argc - first_word_idx);
    words = xmalloc(sizeof(*words) * word_size);
    for (size_t i = 0; i < word_size; i++) {
        char *src = argv[first_word_idx + (int)i];
        size_t raw_len = strlen(src);
        words[i].raw = src;
        words[i].raw_len = raw_len;
        words[i].raw_one = raw_len == 1;
        words[i].raw_pal_multi = pal_multi(src, raw_len);
        words[i].has_comma = false;
        words[i].p1 = NULL;
        words[i].p2 = NULL;
        words[i].p1_len = 0;
        words[i].p2_len = 0;
        words[i].p1_one = false;
        words[i].p2_one = false;
        words[i].p1_pal_multi = false;
        words[i].p2_pal_multi = false;
        char *comma = strchr(src, ',');
        if (!comma) {
            continue;
        }
        char *after = comma + 1;
        char *comma2 = strchr(after, ',');
        size_t a = (size_t)(comma - src);
        size_t b = comma2 ? (size_t)(comma2 - after) : strlen(after);
        if (!a || !b) {
            diex("bad comma word");
        }
        if (a + b >= BUFF) {
            diex("BUFF too small for comma word");
        }
        words[i].has_comma = true;
        words[i].p1 = xstrndup2(src, a);
        words[i].p1_len = a;
        words[i].p1_one = a == 1;
        words[i].p1_pal_multi = pal_multi(words[i].p1, a);
        words[i].p2 = xmalloc(a + b + 1);
        memcpy(words[i].p2, src, a);
        memcpy(words[i].p2 + a, after, b);
        words[i].p2[a + b] = '\0';
        words[i].p2_len = a + b;
        words[i].p2_one = a + b == 1;
        words[i].p2_pal_multi = pal_multi(words[i].p2, a + b);
    }
}

static void free_words(void)
{
    if (!words) {
        return;
    }
    for (size_t i = 0; i < word_size; i++) {
        free(words[i].p1);
        free(words[i].p2);
    }
    free(words);
}


static struct option long_options[] = {
    {"upper", required_argument, 0, 'u'},
    {"last", required_argument, 0, 'l'},
    {"only_transformations", no_argument, 0, 'p'},
    {"reverse", required_argument, 0, 'r'},
    {"memory", no_argument, 0, 'x'},
    {"leet", required_argument, 0, 'k'},
    {"connectors", required_argument, 0, 'c'},
    {"start", required_argument, 0, 's'},
    {"end", required_argument, 0, 'e'},
    {"output", required_argument, 0, 'o'},
    {"repeat", no_argument, 0, 'R'},
    {0, 0, 0, 0}
};

int main(int argc, char **argv)
{
    int c;
    int option_index = 0;
    const char *out_path = "out.txt";

    while ((c = getopt_long(argc, argv, "u:l:pk:c:s:e:r:o:xR", long_options, &option_index)) != -1) {
        switch (c) {
        case 'r': {
            if (!strcmp(optarg, "full")) {
                bool_modifiers.reverse_full = true;
            } else if (!strcmp(optarg, "words")) {
                bool_modifiers.reverse_words = true;
            } else {
                diex("bad reverse mode");
            }
            break;
        }
        case 'k': {
            if (!strcmp(optarg, "full")) {
                bool_modifiers.leet_full = true;
            } else if (!strcmp(optarg, "vowel")) {
                bool_modifiers.leet_vowel = true;
            } else {
                diex("bad leet mode");
            }
            break;
        }
        case 'u': {
            if (!strcmp(optarg, "full")) {
                bool_modifiers.upper_full = true;
            } else if (!strcmp(optarg, "first")) {
                bool_modifiers.upper_first = true;
            } else {
                diex("bad upper mode");
            }
            break;
        }
        case 'p': {
            bool_modifiers.only_transform = true;
            break;
        }
        case 'x': {
            break;
        }
        case 'R': {
            opt_repeat = true;
            break;
        }
        case 'c': {
            connector_chars = optarg;
            connectors_size = strlen(optarg);
            break;
        }
        case 'l': {
            parse_last(optarg);
            break;
        }
        case 's': {
            min_len = (size_t)parse_u64(optarg, "bad min length");
            break;
        }
        case 'e': {
            max_len = (size_t)parse_u64(optarg, "bad max length");
            break;
        }
        case 'o': {
            out_path = optarg;
            break;
        }
        default: {
            diex("bad parameters");
        }
        }
    }
    if (optind == argc) {
        diex("words not provided");
    }
    if (!min_len || !max_len) {
        diex("start/end required");
    }
    if (max_len < min_len) {
        diex("max_len must be >= min_len");
    }
    parse_words(argv, optind, argc);
    if (!opt_repeat && max_len > word_size) {
        max_len = word_size;
    }
    init_leet();
    init_modes();
    static char outbuf[OUT_BUFSZ];
    Out out;
    out_open(&out, out_path, outbuf, sizeof outbuf, OUT_PREALLOC_SIZE);
    Word *selected[max_len];
    if (opt_repeat) {
        gen_repeats(&out, selected);
    } else {
        gen_subsets(&out, 0, 0, selected);
    }
    out_close(&out);
    free_words();
    free(last);
    free(last_len);
    return 0;
}
