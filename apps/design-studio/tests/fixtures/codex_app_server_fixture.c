#define _POSIX_C_SOURCE 200809L

#include <pthread.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>


static pthread_mutex_t output_lock = PTHREAD_MUTEX_INITIALIZER;
static volatile bool interrupted = false;
static unsigned int turn_counter = 0;


struct turn_work {
    char cwd[4096];
    char turn_id[64];
    bool long_running;
};


static void send_line(const char *line) {
    pthread_mutex_lock(&output_lock);
    fputs(line, stdout);
    fputc('\n', stdout);
    fflush(stdout);
    pthread_mutex_unlock(&output_lock);
}


static void sleep_milliseconds(long milliseconds) {
    struct timespec duration = {
        .tv_sec = milliseconds / 1000,
        .tv_nsec = (milliseconds % 1000) * 1000000,
    };
    nanosleep(&duration, NULL);
}


static void response(const char *id, const char *result) {
    char output[2048];
    snprintf(output, sizeof(output), "{\"jsonrpc\":\"2.0\",\"id\":%s,\"result\":%s}", id, result);
    send_line(output);
}


static void extract_id(const char *line, char *output, size_t output_size) {
    const char *cursor = strstr(line, "\"id\"");
    if (cursor == NULL || (cursor = strchr(cursor, ':')) == NULL) {
        snprintf(output, output_size, "null");
        return;
    }
    cursor += 1;
    while (*cursor == ' ' || *cursor == '\t') cursor += 1;
    size_t length = 0;
    if (*cursor == '\"') {
        output[length++] = *cursor++;
        while (*cursor != '\0' && length + 2 < output_size) {
            output[length++] = *cursor;
            if (*cursor == '\\' && cursor[1] != '\0') output[length++] = *++cursor;
            if (*cursor++ == '\"') break;
        }
    } else {
        while (*cursor != '\0' && *cursor != ',' && *cursor != '}' && length + 1 < output_size) {
            output[length++] = *cursor++;
        }
    }
    output[length] = '\0';
}


static bool extract_string(const char *line, const char *key, char *output, size_t output_size) {
    char marker[128];
    snprintf(marker, sizeof(marker), "\"%s\"", key);
    const char *cursor = strstr(line, marker);
    if (cursor == NULL || (cursor = strchr(cursor, ':')) == NULL) return false;
    cursor += 1;
    while (*cursor == ' ' || *cursor == '\t') cursor += 1;
    if (*cursor++ != '\"') return false;
    size_t length = 0;
    while (*cursor != '\0' && *cursor != '\"' && length + 1 < output_size) {
        if (*cursor == '\\') {
            cursor += 1;
            if (*cursor == '\0') break;
            if (*cursor == 'n') output[length++] = '\n';
            else if (*cursor == 't') output[length++] = '\t';
            else output[length++] = *cursor;
            cursor += 1;
            continue;
        }
        output[length++] = *cursor++;
    }
    output[length] = '\0';
    return *cursor == '\"';
}


static void *complete_turn(void *raw_work) {
    struct turn_work *work = raw_work;
    char message[8192];
    snprintf(
        message,
        sizeof(message),
        "{\"jsonrpc\":\"2.0\",\"method\":\"turn/started\",\"params\":{\"turn\":{\"id\":\"%s\",\"status\":\"inProgress\"}}}",
        work->turn_id
    );
    send_line(message);
    sleep_milliseconds(500);
    snprintf(
        message,
        sizeof(message),
        "{\"jsonrpc\":\"2.0\",\"method\":\"item/agentMessage/delta\",\"params\":{\"itemId\":\"message-%s\",\"delta\":\"Maverick E2E incremental result. streaming proof streaming proof streaming proof streaming proof streaming proof streaming proof \"}}",
        work->turn_id
    );
    send_line(message);
    if (work->long_running) {
        for (int attempt = 0; attempt < 300 && !interrupted; attempt += 1) sleep_milliseconds(100);
        snprintf(
            message,
            sizeof(message),
            "{\"jsonrpc\":\"2.0\",\"method\":\"turn/completed\",\"params\":{\"turn\":{\"id\":\"%s\",\"status\":\"interrupted\"}}}",
            work->turn_id
        );
        send_line(message);
        free(work);
        return NULL;
    }
    char output_path[4608];
    snprintf(output_path, sizeof(output_path), "%s/index.html", work->cwd);
    FILE *artifact = fopen(output_path, "w");
    if (artifact != NULL) {
        fputs(
            "<!doctype html><html><head><meta charset=\"utf-8\"><title>Maverick WP10</title></head>"
            "<body><main>Maverick real runtime file proof</main></body></html>\n",
            artifact
        );
        fclose(artifact);
    }
    snprintf(
        message,
        sizeof(message),
        "{\"jsonrpc\":\"2.0\",\"method\":\"item/completed\",\"params\":{\"item\":{\"id\":\"message-%s\",\"type\":\"agentMessage\",\"text\":\"Maverick E2E incremental result. Artifact ready.\"}}}",
        work->turn_id
    );
    send_line(message);
    snprintf(
        message,
        sizeof(message),
        "{\"jsonrpc\":\"2.0\",\"method\":\"turn/completed\",\"params\":{\"turn\":{\"id\":\"%s\",\"status\":\"completed\"}}}",
        work->turn_id
    );
    send_line(message);
    free(work);
    return NULL;
}


int main(void) {
    char *line = NULL;
    size_t capacity = 0;
    while (getline(&line, &capacity, stdin) >= 0) {
        char id[256];
        char method[128] = "";
        extract_id(line, id, sizeof(id));
        extract_string(line, "method", method, sizeof(method));
        if (strcmp(method, "initialize") == 0) {
            response(id, "{\"serverInfo\":{\"name\":\"maverick-wp10-fixture\",\"version\":\"1\"}}");
        } else if (
            strcmp(method, "thread/start") == 0
            || strcmp(method, "thread/resume") == 0
        ) {
            response(id, "{\"thread\":{\"id\":\"thread-maverick-wp10\"}}");
        } else if (strcmp(method, "turn/start") == 0) {
            struct turn_work *work = calloc(1, sizeof(*work));
            if (work == NULL) return 2;
            extract_string(line, "cwd", work->cwd, sizeof(work->cwd));
            work->long_running = strstr(line, "MAVERICK_E2E_LONG") != NULL;
            interrupted = false;
            snprintf(work->turn_id, sizeof(work->turn_id), "turn-%u", ++turn_counter);
            char result[256];
            snprintf(result, sizeof(result), "{\"turn\":{\"id\":\"%s\"}}", work->turn_id);
            response(id, result);
            pthread_t worker;
            if (pthread_create(&worker, NULL, complete_turn, work) != 0) return 3;
            pthread_detach(worker);
        } else if (strcmp(method, "turn/interrupt") == 0) {
            interrupted = true;
            response(id, "{}");
        } else {
            response(id, "{}");
        }
    }
    free(line);
    return 0;
}
