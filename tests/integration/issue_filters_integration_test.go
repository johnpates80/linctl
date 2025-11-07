package integration_test

import (
    "bytes"
    "encoding/json"
    "fmt"
    "os"
    "os/exec"
    "path/filepath"
    "strings"
    "testing"
)

type Issue struct {
    Identifier string `json:"identifier"`
    Title      string `json:"title"`
    Project    *struct{
        ID   string `json:"id"`
        Name string `json:"name"`
    } `json:"project"`
    Labels *struct{
        Nodes []struct{
            ID   string `json:"id"`
            Name string `json:"name"`
        } `json:"nodes"`
    } `json:"labels"`
}

// buildBinary builds the linctl binary in a temp dir and returns its path.
func buildBinary(t *testing.T) string {
    t.Helper()
    tmp := t.TempDir()
    bin := filepath.Join(tmp, "linctl")
    cmd := exec.Command("go", "build", "-o", bin, ".")
    cmd.Env = os.Environ()
    out, err := cmd.CombinedOutput()
    if err != nil {
        t.Fatalf("failed to build linctl: %v\n%s", err, string(out))
    }
    return bin
}

// writeAuthFile writes ~/.linctl-auth.json in a temp HOME with the given API key.
func writeAuthFile(t *testing.T, apiKey string) string {
    t.Helper()
    home := t.TempDir()
    authPath := filepath.Join(home, ".linctl-auth.json")
    if err := os.WriteFile(authPath, []byte(fmt.Sprintf("{\n  \"api_key\": \"%s\"\n}\n", apiKey)), 0600); err != nil {
        t.Fatalf("failed to write auth file: %v", err)
    }
    return home
}

func runCLIJSON(t *testing.T, bin string, home string, args ...string) ([]Issue, string) {
    t.Helper()
    a := append([]string{"issue", "list"}, args...)
    a = append(a, "--json")
    cmd := exec.Command(bin, a...)
    // Ensure CLI uses temp HOME for auth
    env := os.Environ()
    // Override HOME
    env = append(env, fmt.Sprintf("HOME=%s", home))
    cmd.Env = env
    var stdout, stderr bytes.Buffer
    cmd.Stdout = &stdout
    cmd.Stderr = &stderr
    err := cmd.Run()
    outStr := stdout.String()
    if err != nil {
        // Some error responses are emitted as JSON via stdout; prefer stdout
        t.Fatalf("linctl failed: %v\nSTDOUT:\n%s\nSTDERR:\n%s", err, outStr, stderr.String())
    }
    // Handle informational objects like {"info":"No issues found"}
    if strings.HasPrefix(strings.TrimSpace(outStr), "{") {
        // Return empty issues and the raw string for inspection
        return nil, outStr
    }
    var issues []Issue
    if err := json.Unmarshal(stdout.Bytes(), &issues); err != nil {
        t.Fatalf("failed to parse JSON: %v\n%s", err, outStr)
    }
    return issues, outStr
}

func labelSet(iss Issue) map[string]struct{} {
    m := map[string]struct{}{}
    if iss.Labels != nil {
        for _, n := range iss.Labels.Nodes {
            m[strings.ToLower(n.Name)] = struct{}{}
        }
    }
    return m
}

func TestIntegration_ProjectFilter(t *testing.T) {
    apiKey := os.Getenv("LINEAR_TEST_API_KEY")
    projectID := os.Getenv("LINEAR_TEST_PROJECT_ID")
    if apiKey == "" || projectID == "" {
        t.Skip("set LINEAR_TEST_API_KEY and LINEAR_TEST_PROJECT_ID to run this test")
    }
    bin := buildBinary(t)
    home := writeAuthFile(t, apiKey)
    issues, _ := runCLIJSON(t, bin, home, "--project", projectID, "--limit", "10", "--newer-than", "all_time")
    if len(issues) == 0 {
        t.Skip("no issues returned for project; skipping")
    }
    for _, is := range issues {
        if is.Project == nil || is.Project.ID != projectID {
            t.Fatalf("issue %s missing expected project %s (got %+v)", is.Identifier, projectID, is.Project)
        }
    }
}

func TestIntegration_LabelAny(t *testing.T) {
    apiKey := os.Getenv("LINEAR_TEST_API_KEY")
    vals := os.Getenv("LINEAR_TEST_LABELS_ANY") // comma-separated label names
    if apiKey == "" || strings.TrimSpace(vals) == "" {
        t.Skip("set LINEAR_TEST_API_KEY and LINEAR_TEST_LABELS_ANY (comma-separated) to run this test")
    }
    names := strings.Split(vals, ",")
    for i := range names {
        names[i] = strings.ToLower(strings.TrimSpace(names[i]))
    }
    bin := buildBinary(t)
    home := writeAuthFile(t, apiKey)
    issues, _ := runCLIJSON(t, bin, home, "--label-any", vals, "--limit", "10", "--newer-than", "all_time")
    if len(issues) == 0 {
        t.Skip("no issues returned for label-any; skipping")
    }
    for _, is := range issues {
        have := labelSet(is)
        ok := false
        for _, n := range names {
            if _, exists := have[n]; exists {
                ok = true
                break
            }
        }
        if !ok {
            t.Fatalf("issue %s missing any of required labels %v (have: %v)", is.Identifier, names, have)
        }
    }
}

func TestIntegration_LabelAND(t *testing.T) {
    apiKey := os.Getenv("LINEAR_TEST_API_KEY")
    vals := os.Getenv("LINEAR_TEST_LABELS_ALL") // comma-separated label names
    if apiKey == "" || strings.TrimSpace(vals) == "" {
        t.Skip("set LINEAR_TEST_API_KEY and LINEAR_TEST_LABELS_ALL (comma-separated) to run this test")
    }
    names := strings.Split(vals, ",")
    for i := range names {
        names[i] = strings.ToLower(strings.TrimSpace(names[i]))
    }
    bin := buildBinary(t)
    home := writeAuthFile(t, apiKey)
    issues, _ := runCLIJSON(t, bin, home, "--label", vals, "--limit", "10", "--newer-than", "all_time")
    if len(issues) == 0 {
        t.Skip("no issues returned for label AND; skipping")
    }
    for _, is := range issues {
        have := labelSet(is)
        for _, n := range names {
            if _, exists := have[n]; !exists {
                t.Fatalf("issue %s missing required label %q (have: %v)", is.Identifier, n, have)
            }
        }
    }
}

func TestIntegration_LabelNOT(t *testing.T) {
    apiKey := os.Getenv("LINEAR_TEST_API_KEY")
    vals := os.Getenv("LINEAR_TEST_LABELS_NOT") // comma-separated label names
    if apiKey == "" || strings.TrimSpace(vals) == "" {
        t.Skip("set LINEAR_TEST_API_KEY and LINEAR_TEST_LABELS_NOT (comma-separated) to run this test")
    }
    names := strings.Split(vals, ",")
    for i := range names {
        names[i] = strings.ToLower(strings.TrimSpace(names[i]))
    }
    bin := buildBinary(t)
    home := writeAuthFile(t, apiKey)
    issues, _ := runCLIJSON(t, bin, home, "--label-not", vals, "--limit", "10", "--newer-than", "all_time")
    if len(issues) == 0 {
        t.Skip("no issues returned for label NOT; skipping")
    }
    for _, is := range issues {
        have := labelSet(is)
        for _, n := range names {
            if _, exists := have[n]; exists {
                t.Fatalf("issue %s unexpectedly contains excluded label %q", is.Identifier, n)
            }
        }
    }
}

func TestIntegration_Unlabeled(t *testing.T) {
    apiKey := os.Getenv("LINEAR_TEST_API_KEY")
    if apiKey == "" {
        t.Skip("set LINEAR_TEST_API_KEY to run this test")
    }
    bin := buildBinary(t)
    home := writeAuthFile(t, apiKey)
    issues, info := runCLIJSON(t, bin, home, "--unlabeled", "--limit", "10", "--newer-than", "all_time")
    if issues == nil {
        // e.g. {"info":"No issues found"} — nothing to validate
        t.Skipf("unlabeled returned no issues: %s", info)
    }
    for _, is := range issues {
        if is.Labels != nil && len(is.Labels.Nodes) > 0 {
            t.Fatalf("issue %s unexpectedly has labels", is.Identifier)
        }
    }
}

