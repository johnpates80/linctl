package cmd

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/dorkitude/linctl/pkg/api"
)

func TestIssueUpdateCmd_LabelFlags_Help(t *testing.T) {
	usage := issueUpdateCmd.UsageString()
	checks := []string{
		"--label", "Set labels exactly", "Empty string clears", "Takes precedence",
		"--add-label", "--remove-label",
	}
	for _, want := range checks {
		if !strings.Contains(usage, want) {
			t.Fatalf("issue update help missing %q. got:\n%s", want, usage)
		}
	}
}

func TestIssueCreateCmd_LabelFlag_Help(t *testing.T) {
	usage := issueCreateCmd.UsageString()
	if !strings.Contains(usage, "--label") || !strings.Contains(usage, "Comma-separated labels") {
		t.Fatalf("issue create help missing label flag/help. got:\n%s", usage)
	}
}

// Minimal mock GraphQL server for issueLabels query
func newMockLabelsServer(t *testing.T, labels []map[string]any) *httptest.Server {
	t.Helper()
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		var body struct {
			Query string `json:"query"`
		}
		_ = json.NewDecoder(r.Body).Decode(&body)
		if strings.Contains(body.Query, "issueLabels") {
			_ = json.NewEncoder(w).Encode(map[string]any{
				"data": map[string]any{
					"issueLabels": map[string]any{
						"nodes": labels,
					},
				},
			})
			return
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"data": map[string]any{}})
	}))
}

func TestLookupIssueLabelIDsByNames_TrimDedupAndMatch(t *testing.T) {
	srv := newMockLabelsServer(t, []map[string]any{
		{"id": "L_bug", "name": "Bug", "color": "#f00"},
		{"id": "L_api", "name": "API", "color": "#0f0"},
	})
	defer srv.Close()

	client := api.NewClientWithURL(srv.URL, "Bearer test")
	ids, err := lookupIssueLabelIDsByNames(context.Background(), client, "  Bug , API, bug  ")
	if err != nil {
		t.Fatalf("lookup returned error: %v", err)
	}
	// Expect deduped, matched IDs in input order of unique tokens
	if len(ids) != 2 {
		t.Fatalf("expected 2 IDs, got %d (%v)", len(ids), ids)
	}
	if ids[0] != "L_bug" || ids[1] != "L_api" {
		t.Fatalf("unexpected IDs: %v", ids)
	}
}

func TestLookupIssueLabelIDsByNames_UnknownWithSuggestions(t *testing.T) {
	srv := newMockLabelsServer(t, []map[string]any{
		{"id": "L_bug", "name": "Bug", "color": "#f00"},
		{"id": "L_backend", "name": "Backend", "color": "#0f0"},
		{"id": "L_frontend", "name": "Frontend", "color": "#00f"},
	})
	defer srv.Close()

	client := api.NewClientWithURL(srv.URL, "Bearer test")
	_, err := lookupIssueLabelIDsByNames(context.Background(), client, "bkg")
	if err == nil {
		t.Fatalf("expected error for unknown label, got nil")
	}
	// Error should mention not found and include a suggestion phrase
	msg := err.Error()
	if !strings.Contains(msg, "issue label not found") {
		t.Fatalf("unexpected error message: %s", msg)
	}
}
