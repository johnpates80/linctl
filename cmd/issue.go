package cmd

import (
	"context"
	"fmt"
	"os"
	"regexp"
	"sort"
	"strings"

	"github.com/raegislabs/linctl/pkg/api"
	"github.com/raegislabs/linctl/pkg/auth"
	"github.com/raegislabs/linctl/pkg/output"
	"github.com/raegislabs/linctl/pkg/utils"
	"github.com/fatih/color"
	"github.com/spf13/cobra"
	"github.com/spf13/viper"
)

var uuidRegexp = regexp.MustCompile(`^[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}$`)

func isValidUUID(s string) bool { return uuidRegexp.MatchString(s) }

func isProjectNotFoundErr(err error) bool {
	if err == nil {
		return false
	}
	e := strings.ToLower(err.Error())
	if !strings.Contains(e, "not found") {
		return false
	}
	return strings.Contains(e, "project") || strings.Contains(e, "projectid")
}

func isIssueNotFoundErr(err error) bool {
    if err == nil { return false }
    e := strings.ToLower(err.Error())
    if !strings.Contains(e, "not found") { return false }
    return strings.Contains(e, "issue") || strings.Contains(e, "parent") || strings.Contains(e, "id")
}

// buildProjectInput normalizes a --project flag value to a GraphQL input value.
// Returns (value, ok, err):
// - ok=false means no input should be set (flag empty / not provided)
// - value=nil with ok=true means explicitly unset (unassigned)
// - value=string (uuid) with ok=true means assign to that project
func buildProjectInput(projectFlag string) (interface{}, bool, error) {
	switch strings.TrimSpace(projectFlag) {
	case "":
		return nil, false, nil
	case "unassigned":
		return nil, true, nil
	default:
		if !isValidUUID(projectFlag) {
			return nil, false, fmt.Errorf("Invalid project ID format: %s", projectFlag)
		}
		return projectFlag, true, nil
	}
}

// levenshtein computes the Levenshtein distance between two strings.
func levenshtein(a, b string) int {
	ra, rb := []rune(a), []rune(b)
	la, lb := len(ra), len(rb)
	if la == 0 {
		return lb
	}
	if lb == 0 {
		return la
	}
	dp := make([]int, lb+1)
	for j := 0; j <= lb; j++ {
		dp[j] = j
	}
	for i := 1; i <= la; i++ {
		prev := i - 1
		dp[0] = i
		for j := 1; j <= lb; j++ {
			temp := dp[j]
			cost := 0
			if ra[i-1] != rb[j-1] {
				cost = 1
			}
			// min of delete, insert, substitute
			del := dp[j] + 1
			ins := dp[j-1] + 1
			sub := prev + cost
			m := del
			if ins < m {
				m = ins
			}
			if sub < m {
				m = sub
			}
			dp[j] = m
			prev = temp
		}
	}
	return dp[lb]
}

// closestMatches returns up to k label names with the smallest edit distance to target.
func closestMatches(target string, candidates []string, k int) []string {
	type pair struct {
		name string
		d    int
	}
	target = strings.ToLower(strings.TrimSpace(target))
	arr := make([]pair, 0, len(candidates))
	for _, c := range candidates {
		c2 := strings.ToLower(strings.TrimSpace(c))
		if c2 == "" {
			continue
		}
		arr = append(arr, pair{name: c, d: levenshtein(target, c2)})
	}
	sort.Slice(arr, func(i, j int) bool { return arr[i].d < arr[j].d })
	n := k
	if len(arr) < k {
		n = len(arr)
	}
	out := make([]string, 0, n)
	for i := 0; i < n; i++ {
		out = append(out, arr[i].name)
	}
	return out
}

// lookupIssueLabelIDsByNames looks up issue label IDs from comma-separated names.
// - Trims whitespace, deduplicates case-insensitively
// - Returns helpful error with up to 3 closest matches for unknown labels
func lookupIssueLabelIDsByNames(ctx context.Context, client *api.Client, names string) ([]string, error) {
	if strings.TrimSpace(names) == "" {
		return []string{}, nil
	}

	// Split, trim, dedup (case-insensitive)
	raw := strings.Split(names, ",")
	seen := make(map[string]struct{})
	cleaned := make([]string, 0, len(raw))
	for _, n := range raw {
		t := strings.TrimSpace(n)
		if t == "" {
			continue
		}
		key := strings.ToLower(t)
		if _, ok := seen[key]; ok {
			continue
		}
		seen[key] = struct{}{}
		cleaned = append(cleaned, t)
	}

	labels, err := client.GetIssueLabels(ctx)
	if err != nil {
		return nil, fmt.Errorf("failed to get issue labels: %v", err)
	}
	nameToID := make(map[string]string, len(labels.Nodes))
	allNames := make([]string, 0, len(labels.Nodes))
	for _, l := range labels.Nodes {
		lower := strings.ToLower(l.Name)
		nameToID[lower] = l.ID
		allNames = append(allNames, l.Name)
	}

	ids := make([]string, 0, len(cleaned))
	for _, n := range cleaned {
		id, ok := nameToID[strings.ToLower(n)]
		if !ok {
			// Build suggestions list
			sug := closestMatches(n, allNames, 3)
			if len(sug) > 0 {
				return nil, fmt.Errorf("issue label not found: '%s' (did you mean: %s)", n, strings.Join(sug, ", "))
			}
			return nil, fmt.Errorf("issue label not found: '%s'", n)
		}
		ids = append(ids, id)
	}
	return ids, nil
}

// issueCmd represents the issue command
var issueCmd = &cobra.Command{
	Use:   "issue",
	Short: "Manage Linear issues",
	Long: `Create, list, update, and manage Linear issues.

Examples:
  linctl issue list --assignee me --state "In Progress"
  linctl issue ls -a me -s "In Progress"
  linctl issue list --include-completed  # Show all issues including completed
  linctl issue list --newer-than 3_weeks_ago  # Show issues from last 3 weeks
  linctl issue search "login bug" --team ENG
  linctl issue get LIN-123
  linctl issue create --title "Bug fix" --team ENG`,
}

var issueListCmd = &cobra.Command{
	Use:     "list",
	Aliases: []string{"ls"},
	Short:   "List issues",
	Long:    `List Linear issues with optional filtering.`,
	Run: func(cmd *cobra.Command, args []string) {
		plaintext := viper.GetBool("plaintext")
		jsonOut := viper.GetBool("json")

		authHeader, err := auth.GetAuthHeader()
		if err != nil {
			output.Error("Not authenticated. Run 'linctl auth' first.", plaintext, jsonOut)
			os.Exit(1)
		}

    client := api.NewClient(authHeader)

    // Build filter from flags (includes optional label/project, label operators)
    filter, requiredAllIDs, anyIDs, notIDs, wantUnlabeled, parentID, wantHasParent, wantNoParent := buildIssueFilter(cmd, client)

		limit, _ := cmd.Flags().GetInt("limit")
		if limit == 0 {
			limit = 50
		}

		// Get sort option
		sortBy, _ := cmd.Flags().GetString("sort")
		orderBy := ""
		if sortBy != "" {
			switch sortBy {
			case "created", "createdAt":
				orderBy = "createdAt"
			case "updated", "updatedAt":
				orderBy = "updatedAt"
			case "linear":
				// Use empty string for Linear's default sort
				orderBy = ""
			default:
				output.Error(fmt.Sprintf("Invalid sort option: %s. Valid options are: linear, created, updated", sortBy), plaintext, jsonOut)
				os.Exit(1)
			}
		}

    issues, err := client.GetIssues(context.Background(), filter, limit, "", orderBy)
    if err != nil {
        output.Error(fmt.Sprintf("Failed to fetch issues: %v", err), plaintext, jsonOut)
        os.Exit(1)
    }

    // Apply post-filters for labels (AND/OR/NOT/unlabeled)
    issues = filterIssuesAdvanced(issues, requiredAllIDs, anyIDs, notIDs, wantUnlabeled)
    issues = filterIssuesByParent(issues, parentID, wantHasParent, wantNoParent)

    renderIssueCollection(issues, plaintext, jsonOut, "No issues found", "issues", "# Issues")
},
}

func renderIssueCollection(issues *api.Issues, plaintext, jsonOut bool, emptyMessage, summaryLabel, plaintextTitle string) {
	if len(issues.Nodes) == 0 {
		output.Info(emptyMessage, plaintext, jsonOut)
		return
	}

	if jsonOut {
		output.JSON(issues.Nodes)
		return
	}

    if plaintext {
        fmt.Println(plaintextTitle)
        for _, issue := range issues.Nodes {
            fmt.Printf("## %s\n", issue.Title)
            fmt.Printf("- **ID**: %s\n", issue.Identifier)
            if issue.State != nil {
                fmt.Printf("- **State**: %s\n", issue.State.Name)
            }
            if issue.Assignee != nil {
                fmt.Printf("- **Assignee**: %s\n", issue.Assignee.Name)
            } else {
                fmt.Printf("- **Assignee**: Unassigned\n")
            }
            if issue.Team != nil {
                fmt.Printf("- **Team**: %s\n", issue.Team.Key)
            }
            if issue.Project != nil {
                fmt.Printf("- **Project**: %s\n", issue.Project.Name)
            }
            if issue.Parent != nil && issue.Parent.Identifier != "" {
                fmt.Printf("- **Parent**: %s\n", issue.Parent.Identifier)
            }
            // Labels (show all names or None)
            if issue.Labels != nil && len(issue.Labels.Nodes) > 0 {
                names := make([]string, 0, len(issue.Labels.Nodes))
                for _, l := range issue.Labels.Nodes {
                    names = append(names, l.Name)
                }
                fmt.Printf("- **Labels**: %s\n", strings.Join(names, ", "))
            } else {
                fmt.Printf("- **Labels**: None\n")
            }
            fmt.Printf("- **Created**: %s\n", issue.CreatedAt.Format("2006-01-02"))
            fmt.Printf("- **URL**: %s\n", issue.URL)
            if issue.Description != "" {
                fmt.Printf("- **Description**: %s\n", issue.Description)
            }
            fmt.Println()
        }
        fmt.Printf("\nTotal: %d %s\n", len(issues.Nodes), summaryLabel)
        return
    }

    headers := []string{"Title", "State", "Assignee", "Team", "Project", "Parent", "Labels", "Created", "URL"}
	rows := make([][]string, len(issues.Nodes))

	for i, issue := range issues.Nodes {
		assignee := "Unassigned"
		if issue.Assignee != nil {
			assignee = issue.Assignee.Name
		}

		team := ""
		if issue.Team != nil {
			team = issue.Team.Key
		}

        project := ""
        if issue.Project != nil {
            project = truncateString(issue.Project.Name, 25)
        }

        // Build labels string: up to 3 labels, comma-separated
        labels := "-"
        if issue.Labels != nil && len(issue.Labels.Nodes) > 0 {
            count := len(issue.Labels.Nodes)
            max := 3
            if count < max {
                max = count
            }
            names := make([]string, 0, max)
            for i := 0; i < max; i++ {
                names = append(names, issue.Labels.Nodes[i].Name)
            }
            labels = strings.Join(names, ", ")
            if count > max {
                // Indicate more labels exist; still truncate to fit table
                labels = labels + fmt.Sprintf(" +%d", count-max)
            }
            labels = truncateString(labels, 25)
        }

        // Parent identifier (if any)
        parent := ""
        if issue.Parent != nil && issue.Parent.Identifier != "" {
            parent = issue.Parent.Identifier
        }

        state := ""
        if issue.State != nil {
            state = issue.State.Name
            var stateColor *color.Color
			switch issue.State.Type {
			case "triage":
				stateColor = color.New(color.FgMagenta)
			case "backlog":
				stateColor = color.New(color.FgCyan)
			case "unstarted":
				stateColor = color.New(color.FgWhite)
			case "started":
				stateColor = color.New(color.FgBlue)
			case "completed":
				stateColor = color.New(color.FgGreen)
			case "canceled":
				stateColor = color.New(color.FgRed)
			default:
				stateColor = color.New(color.FgWhite)
			}
			state = stateColor.Sprint(state)
		}

		if issue.Assignee == nil {
			assignee = color.New(color.FgYellow).Sprint(assignee)
		}

        rows[i] = []string{
            truncateString(issue.Title, 40),
            state,
            assignee,
            team,
            project,
            parent,
            labels,
            issue.CreatedAt.Format("2006-01-02"),
            issue.URL,
        }
	}

	tableData := output.TableData{
		Headers: headers,
		Rows:    rows,
	}

	output.Table(tableData, false, false)

	fmt.Printf("\n%s %d %s\n",
		color.New(color.FgGreen).Sprint("✓"),
		len(issues.Nodes),
		summaryLabel)

	if issues.PageInfo.HasNextPage {
		fmt.Printf("%s Use --limit to see more results\n",
			color.New(color.FgYellow).Sprint("ℹ️"))
	}
}

var issueSearchCmd = &cobra.Command{
	Use:     "search [query]",
	Aliases: []string{"find"},
	Short:   "Search issues by keyword",
	Long: `Perform a full-text search across Linear issues.

Examples:
  linctl issue search "payment outage"
  linctl issue search "auth token" --team ENG --include-completed
  linctl issue search "customer:" --json`,
	Args: cobra.MinimumNArgs(1),
	Run: func(cmd *cobra.Command, args []string) {
		plaintext := viper.GetBool("plaintext")
		jsonOut := viper.GetBool("json")

		query := strings.TrimSpace(strings.Join(args, " "))
		if query == "" {
			output.Error("Search query is required", plaintext, jsonOut)
			os.Exit(1)
		}

		authHeader, err := auth.GetAuthHeader()
		if err != nil {
			output.Error("Not authenticated. Run 'linctl auth' first.", plaintext, jsonOut)
			os.Exit(1)
		}

    client := api.NewClient(authHeader)

    filter, requiredAllIDs, anyIDs, notIDs, wantUnlabeled, parentID, wantHasParent, wantNoParent := buildIssueFilter(cmd, client)

		limit, _ := cmd.Flags().GetInt("limit")
		if limit == 0 {
			limit = 50
		}

		sortBy, _ := cmd.Flags().GetString("sort")
		orderBy := ""
		if sortBy != "" {
			switch sortBy {
			case "created", "createdAt":
				orderBy = "createdAt"
			case "updated", "updatedAt":
				orderBy = "updatedAt"
			case "linear":
				orderBy = ""
			default:
				output.Error(fmt.Sprintf("Invalid sort option: %s. Valid options are: linear, created, updated", sortBy), plaintext, jsonOut)
				os.Exit(1)
			}
		}

		includeArchived, _ := cmd.Flags().GetBool("include-archived")

    issues, err := client.IssueSearch(context.Background(), query, filter, limit, "", orderBy, includeArchived)
    if err != nil {
        output.Error(fmt.Sprintf("Failed to search issues: %v", err), plaintext, jsonOut)
        os.Exit(1)
    }

    // Apply post-filters for labels (AND/OR/NOT/unlabeled)
    issues = filterIssuesAdvanced(issues, requiredAllIDs, anyIDs, notIDs, wantUnlabeled)
    issues = filterIssuesByParent(issues, parentID, wantHasParent, wantNoParent)

    emptyMsg := fmt.Sprintf("No matches found for %q", query)
    renderIssueCollection(issues, plaintext, jsonOut, emptyMsg, "matches", "# Search Results")
},
}

var issueGetCmd = &cobra.Command{
	Use:     "get [issue-id]",
	Aliases: []string{"show"},
	Short:   "Get issue details",
	Long:    `Get detailed information about a specific issue.`,
	Args:    cobra.ExactArgs(1),
	Run: func(cmd *cobra.Command, args []string) {
		plaintext := viper.GetBool("plaintext")
		jsonOut := viper.GetBool("json")

		authHeader, err := auth.GetAuthHeader()
		if err != nil {
			output.Error("Not authenticated. Run 'linctl auth' first.", plaintext, jsonOut)
			os.Exit(1)
		}

		client := api.NewClient(authHeader)
		issue, err := client.GetIssue(context.Background(), args[0])
		if err != nil {
			output.Error(fmt.Sprintf("Failed to fetch issue: %v", err), plaintext, jsonOut)
			os.Exit(1)
		}

		if jsonOut {
			output.JSON(issue)
			return
		}

		if plaintext {
			fmt.Printf("# %s - %s\n\n", issue.Identifier, issue.Title)

			if issue.Description != "" {
				fmt.Printf("## Description\n%s\n\n", issue.Description)
			}

			fmt.Printf("## Core Details\n")
			fmt.Printf("- **ID**: %s\n", issue.Identifier)
			fmt.Printf("- **Number**: %d\n", issue.Number)
			if issue.State != nil {
				fmt.Printf("- **State**: %s (%s)\n", issue.State.Name, issue.State.Type)
				if issue.State.Description != nil && *issue.State.Description != "" {
					fmt.Printf("  - Description: %s\n", *issue.State.Description)
				}
			}
			if issue.Assignee != nil {
				fmt.Printf("- **Assignee**: %s (%s)\n", issue.Assignee.Name, issue.Assignee.Email)
				if issue.Assignee.DisplayName != "" && issue.Assignee.DisplayName != issue.Assignee.Name {
					fmt.Printf("  - Display Name: %s\n", issue.Assignee.DisplayName)
				}
			} else {
				fmt.Printf("- **Assignee**: Unassigned\n")
			}
			if issue.Creator != nil {
				fmt.Printf("- **Creator**: %s (%s)\n", issue.Creator.Name, issue.Creator.Email)
			}
			if issue.Team != nil {
				fmt.Printf("- **Team**: %s (%s)\n", issue.Team.Name, issue.Team.Key)
				if issue.Team.Description != "" {
					fmt.Printf("  - Description: %s\n", issue.Team.Description)
				}
			}
			fmt.Printf("- **Priority**: %s (%d)\n", priorityToString(issue.Priority), issue.Priority)
			if issue.PriorityLabel != "" {
				fmt.Printf("- **Priority Label**: %s\n", issue.PriorityLabel)
			}
			if issue.Estimate != nil {
				fmt.Printf("- **Estimate**: %.1f\n", *issue.Estimate)
			}

			fmt.Printf("\n## Status & Dates\n")
			fmt.Printf("- **Created**: %s\n", issue.CreatedAt.Format("2006-01-02 15:04:05"))
			fmt.Printf("- **Updated**: %s\n", issue.UpdatedAt.Format("2006-01-02 15:04:05"))
			if issue.TriagedAt != nil {
				fmt.Printf("- **Triaged**: %s\n", issue.TriagedAt.Format("2006-01-02 15:04:05"))
			}
			if issue.CompletedAt != nil {
				fmt.Printf("- **Completed**: %s\n", issue.CompletedAt.Format("2006-01-02 15:04:05"))
			}
			if issue.CanceledAt != nil {
				fmt.Printf("- **Canceled**: %s\n", issue.CanceledAt.Format("2006-01-02 15:04:05"))
			}
			if issue.ArchivedAt != nil {
				fmt.Printf("- **Archived**: %s\n", issue.ArchivedAt.Format("2006-01-02 15:04:05"))
			}
			if issue.DueDate != nil && *issue.DueDate != "" {
				fmt.Printf("- **Due Date**: %s\n", *issue.DueDate)
			}
			if issue.SnoozedUntilAt != nil {
				fmt.Printf("- **Snoozed Until**: %s\n", issue.SnoozedUntilAt.Format("2006-01-02 15:04:05"))
			}

			fmt.Printf("\n## Technical Details\n")
			fmt.Printf("- **Board Order**: %.2f\n", issue.BoardOrder)
			fmt.Printf("- **Sub-Issue Sort Order**: %.2f\n", issue.SubIssueSortOrder)
			if issue.BranchName != "" {
				fmt.Printf("- **Git Branch**: %s\n", issue.BranchName)
			}
			if issue.CustomerTicketCount > 0 {
				fmt.Printf("- **Customer Ticket Count**: %d\n", issue.CustomerTicketCount)
			}
			if len(issue.PreviousIdentifiers) > 0 {
				fmt.Printf("- **Previous Identifiers**: %s\n", strings.Join(issue.PreviousIdentifiers, ", "))
			}
			if issue.IntegrationSourceType != nil && *issue.IntegrationSourceType != "" {
				fmt.Printf("- **Integration Source**: %s\n", *issue.IntegrationSourceType)
			}
			if issue.ExternalUserCreator != nil {
				fmt.Printf("- **External Creator**: %s (%s)\n", issue.ExternalUserCreator.Name, issue.ExternalUserCreator.Email)
			}
			fmt.Printf("- **URL**: %s\n", issue.URL)

			// Project and Cycle Info
			if issue.Project != nil {
				fmt.Printf("\n## Project\n")
				fmt.Printf("- **Name**: %s\n", issue.Project.Name)
				fmt.Printf("- **State**: %s\n", issue.Project.State)
				fmt.Printf("- **Progress**: %.0f%%\n", issue.Project.Progress*100)
				if issue.Project.Health != "" {
					fmt.Printf("- **Health**: %s\n", issue.Project.Health)
				}
				if issue.Project.Description != "" {
					fmt.Printf("- **Description**: %s\n", issue.Project.Description)
				}
			}

			if issue.Cycle != nil {
				fmt.Printf("\n## Cycle\n")
				fmt.Printf("- **Name**: %s (#%d)\n", issue.Cycle.Name, issue.Cycle.Number)
				if issue.Cycle.Description != nil && *issue.Cycle.Description != "" {
					fmt.Printf("- **Description**: %s\n", *issue.Cycle.Description)
				}
				fmt.Printf("- **Period**: %s to %s\n", issue.Cycle.StartsAt, issue.Cycle.EndsAt)
				fmt.Printf("- **Progress**: %.0f%%\n", issue.Cycle.Progress*100)
				if issue.Cycle.CompletedAt != nil {
					fmt.Printf("- **Completed**: %s\n", issue.Cycle.CompletedAt.Format("2006-01-02"))
				}
			}

			// Labels
			if issue.Labels != nil && len(issue.Labels.Nodes) > 0 {
				fmt.Printf("\n## Labels\n")
				for _, label := range issue.Labels.Nodes {
					fmt.Printf("- %s", label.Name)
					if label.Description != nil && *label.Description != "" {
						fmt.Printf(" - %s", *label.Description)
					}
					fmt.Println()
				}
			}

			// Subscribers
			if issue.Subscribers != nil && len(issue.Subscribers.Nodes) > 0 {
				fmt.Printf("\n## Subscribers\n")
				for _, subscriber := range issue.Subscribers.Nodes {
					fmt.Printf("- %s (%s)\n", subscriber.Name, subscriber.Email)
				}
			}

			// Relations
			if issue.Relations != nil && len(issue.Relations.Nodes) > 0 {
				fmt.Printf("\n## Related Issues\n")
				for _, relation := range issue.Relations.Nodes {
					if relation.RelatedIssue != nil {
						relationType := relation.Type
						switch relationType {
						case "blocks":
							relationType = "Blocks"
						case "blocked":
							relationType = "Blocked by"
						case "related":
							relationType = "Related to"
						case "duplicate":
							relationType = "Duplicate of"
						}
						fmt.Printf("- %s: %s - %s", relationType, relation.RelatedIssue.Identifier, relation.RelatedIssue.Title)
						if relation.RelatedIssue.State != nil {
							fmt.Printf(" [%s]", relation.RelatedIssue.State.Name)
						}
						fmt.Println()
					}
				}
			}

			// Reactions
			if len(issue.Reactions) > 0 {
				fmt.Printf("\n## Reactions\n")
				reactionMap := make(map[string][]string)
				for _, reaction := range issue.Reactions {
					reactionMap[reaction.Emoji] = append(reactionMap[reaction.Emoji], reaction.User.Name)
				}
				for emoji, users := range reactionMap {
					fmt.Printf("- %s: %s\n", emoji, strings.Join(users, ", "))
				}
			}

			// Show parent issue if this is a sub-issue
			if issue.Parent != nil {
				fmt.Printf("\n## Parent Issue\n")
				fmt.Printf("- %s: %s\n", issue.Parent.Identifier, issue.Parent.Title)
			}

			// Show sub-issues if any
			if issue.Children != nil && len(issue.Children.Nodes) > 0 {
				fmt.Printf("\n## Sub-issues\n")
				for _, child := range issue.Children.Nodes {
					stateStr := ""
					if child.State != nil {
						switch child.State.Type {
						case "completed", "done":
							stateStr = "[x]"
						case "started", "in_progress":
							stateStr = "[~]"
						case "canceled":
							stateStr = "[-]"
						default:
							stateStr = "[ ]"
						}
					} else {
						stateStr = "[ ]"
					}

					assignee := "Unassigned"
					if child.Assignee != nil {
						assignee = child.Assignee.Name
					}

					fmt.Printf("- %s %s: %s (%s)\n", stateStr, child.Identifier, child.Title, assignee)
				}
			}

			// Show attachments if any
			if issue.Attachments != nil && len(issue.Attachments.Nodes) > 0 {
				fmt.Printf("\n## Attachments\n")
				for _, attachment := range issue.Attachments.Nodes {
					fmt.Printf("- [%s](%s)\n", attachment.Title, attachment.URL)
				}
			}

			// Show recent comments if any
			if issue.Comments != nil && len(issue.Comments.Nodes) > 0 {
				fmt.Printf("\n## Recent Comments\n")
				for _, comment := range issue.Comments.Nodes {
					fmt.Printf("\n### %s - %s\n", comment.User.Name, comment.CreatedAt.Format("2006-01-02 15:04"))
					if comment.EditedAt != nil {
						fmt.Printf("*(edited %s)*\n", comment.EditedAt.Format("2006-01-02 15:04"))
					}
					fmt.Printf("%s\n", comment.Body)
					if comment.Children != nil && len(comment.Children.Nodes) > 0 {
						for _, reply := range comment.Children.Nodes {
							fmt.Printf("\n  **Reply from %s**: %s\n", reply.User.Name, reply.Body)
						}
					}
				}
				fmt.Printf("\n> Use `linctl comment list %s` to see all comments\n", issue.Identifier)
			}

			// Show history
			if issue.History != nil && len(issue.History.Nodes) > 0 {
				fmt.Printf("\n## Recent History\n")
				for _, entry := range issue.History.Nodes {
					fmt.Printf("\n- **%s** by %s", entry.CreatedAt.Format("2006-01-02 15:04"), entry.Actor.Name)
					changes := []string{}

					if entry.FromState != nil && entry.ToState != nil {
						changes = append(changes, fmt.Sprintf("State: %s → %s", entry.FromState.Name, entry.ToState.Name))
					}
					if entry.FromAssignee != nil && entry.ToAssignee != nil {
						changes = append(changes, fmt.Sprintf("Assignee: %s → %s", entry.FromAssignee.Name, entry.ToAssignee.Name))
					} else if entry.FromAssignee != nil && entry.ToAssignee == nil {
						changes = append(changes, fmt.Sprintf("Unassigned from %s", entry.FromAssignee.Name))
					} else if entry.FromAssignee == nil && entry.ToAssignee != nil {
						changes = append(changes, fmt.Sprintf("Assigned to %s", entry.ToAssignee.Name))
					}
					if entry.FromPriority != nil && entry.ToPriority != nil {
						changes = append(changes, fmt.Sprintf("Priority: %s → %s", priorityToString(*entry.FromPriority), priorityToString(*entry.ToPriority)))
					}
					if entry.FromTitle != nil && entry.ToTitle != nil {
						changes = append(changes, fmt.Sprintf("Title: \"%s\" → \"%s\"", *entry.FromTitle, *entry.ToTitle))
					}
					if entry.FromCycle != nil && entry.ToCycle != nil {
						changes = append(changes, fmt.Sprintf("Cycle: %s → %s", entry.FromCycle.Name, entry.ToCycle.Name))
					}
					if entry.FromProject != nil && entry.ToProject != nil {
						changes = append(changes, fmt.Sprintf("Project: %s → %s", entry.FromProject.Name, entry.ToProject.Name))
					}
					if len(entry.AddedLabelIds) > 0 {
						changes = append(changes, fmt.Sprintf("Added %d label(s)", len(entry.AddedLabelIds)))
					}
					if len(entry.RemovedLabelIds) > 0 {
						changes = append(changes, fmt.Sprintf("Removed %d label(s)", len(entry.RemovedLabelIds)))
					}

					if len(changes) > 0 {
						fmt.Printf("\n  - %s", strings.Join(changes, "\n  - "))
					}
					fmt.Println()
				}
			}

			return
		}

		// Rich display
		fmt.Printf("%s %s\n",
			color.New(color.FgCyan, color.Bold).Sprint(issue.Identifier),
			color.New(color.FgWhite, color.Bold).Sprint(issue.Title))

		if issue.Description != "" {
			fmt.Printf("\n%s\n", issue.Description)
		}

		fmt.Printf("\n%s\n", color.New(color.FgYellow).Sprint("Details:"))

		if issue.State != nil {
			stateStr := issue.State.Name
			if issue.State.Type == "completed" && issue.CompletedAt != nil {
				stateStr += fmt.Sprintf(" (%s)", issue.CompletedAt.Format("2006-01-02"))
			}
			fmt.Printf("State: %s\n",
				color.New(color.FgGreen).Sprint(stateStr))
		}

		if issue.Assignee != nil {
			fmt.Printf("Assignee: %s\n",
				color.New(color.FgCyan).Sprint(issue.Assignee.Name))
		} else {
			fmt.Printf("Assignee: %s\n",
				color.New(color.FgRed).Sprint("Unassigned"))
		}

		if issue.Team != nil {
			fmt.Printf("Team: %s\n",
				color.New(color.FgMagenta).Sprint(issue.Team.Name))
		}

		fmt.Printf("Priority: %s\n", priorityToString(issue.Priority))

		// Show project and cycle info
		if issue.Project != nil {
			fmt.Printf("Project: %s (%s)\n",
				color.New(color.FgBlue).Sprint(issue.Project.Name),
				color.New(color.FgWhite, color.Faint).Sprintf("%.0f%%", issue.Project.Progress*100))
		}

		if issue.Cycle != nil {
			fmt.Printf("Cycle: %s\n",
				color.New(color.FgMagenta).Sprint(issue.Cycle.Name))
		}

		fmt.Printf("Created: %s\n", issue.CreatedAt.Format("2006-01-02 15:04:05"))
		fmt.Printf("Updated: %s\n", issue.UpdatedAt.Format("2006-01-02 15:04:05"))

		if issue.DueDate != nil && *issue.DueDate != "" {
			fmt.Printf("Due Date: %s\n",
				color.New(color.FgYellow).Sprint(*issue.DueDate))
		}

		if issue.SnoozedUntilAt != nil {
			fmt.Printf("Snoozed Until: %s\n",
				color.New(color.FgYellow).Sprint(issue.SnoozedUntilAt.Format("2006-01-02 15:04:05")))
		}

		// Show git branch if available
		if issue.BranchName != "" {
			fmt.Printf("Git Branch: %s\n",
				color.New(color.FgGreen).Sprint(issue.BranchName))
		}

		// Show URL
		if issue.URL != "" {
			fmt.Printf("URL: %s\n",
				color.New(color.FgBlue, color.Underline).Sprint(issue.URL))
		}

		// Show parent issue if this is a sub-issue
		if issue.Parent != nil {
			fmt.Printf("\n%s\n", color.New(color.FgYellow).Sprint("Parent Issue:"))
			fmt.Printf("  %s %s\n",
				color.New(color.FgCyan).Sprint(issue.Parent.Identifier),
				issue.Parent.Title)
		}

		// Show sub-issues if any
		if issue.Children != nil && len(issue.Children.Nodes) > 0 {
			fmt.Printf("\n%s\n", color.New(color.FgYellow).Sprint("Sub-issues:"))
			for _, child := range issue.Children.Nodes {
				stateIcon := "○"
				if child.State != nil {
					switch child.State.Type {
					case "completed", "done":
						stateIcon = color.New(color.FgGreen).Sprint("✓")
					case "started", "in_progress":
						stateIcon = color.New(color.FgBlue).Sprint("◐")
					case "canceled":
						stateIcon = color.New(color.FgRed).Sprint("✗")
					}
				}

				assignee := "Unassigned"
				if child.Assignee != nil {
					assignee = child.Assignee.Name
				}

				fmt.Printf("  %s %s %s (%s)\n",
					stateIcon,
					color.New(color.FgCyan).Sprint(child.Identifier),
					child.Title,
					color.New(color.FgWhite, color.Faint).Sprint(assignee))
			}
		}

		// Show attachments if any
		if issue.Attachments != nil && len(issue.Attachments.Nodes) > 0 {
			fmt.Printf("\n%s\n", color.New(color.FgYellow).Sprint("Attachments:"))
			for _, attachment := range issue.Attachments.Nodes {
				fmt.Printf("  📎 %s - %s\n",
					attachment.Title,
					color.New(color.FgBlue, color.Underline).Sprint(attachment.URL))
			}
		}

		// Show recent comments if any
		if issue.Comments != nil && len(issue.Comments.Nodes) > 0 {
			fmt.Printf("\n%s\n", color.New(color.FgYellow).Sprint("Recent Comments:"))
			for _, comment := range issue.Comments.Nodes {
				fmt.Printf("  💬 %s - %s\n",
					color.New(color.FgCyan).Sprint(comment.User.Name),
					color.New(color.FgWhite, color.Faint).Sprint(comment.CreatedAt.Format("2006-01-02 15:04")))
				// Show first line of comment
				lines := strings.Split(comment.Body, "\n")
				if len(lines) > 0 && lines[0] != "" {
					preview := lines[0]
					if len(preview) > 60 {
						preview = preview[:57] + "..."
					}
					fmt.Printf("     %s\n", preview)
				}
			}
			fmt.Printf("\n  %s Use 'linctl comment list %s' to see all comments\n",
				color.New(color.FgWhite, color.Faint).Sprint("→"),
				issue.Identifier)
		}
	},
}

func buildIssueFilter(cmd *cobra.Command, client *api.Client) (map[string]interface{}, []string, []string, []string, bool, string, bool, bool) {
    filter := make(map[string]interface{})
    // Label operator buckets
    requiredLabelIDs := []string{} // --label (AND semantics)
    anyLabelIDs := []string{}      // --label-any (OR semantics)
    notLabelIDs := []string{}      // --label-not (exclude)
    unlabeledOnly := false         // --unlabeled
    // Parent filters
    parentNodeID := ""            // --parent <identifier>
    hasParent := false             // --has-parent
    noParent := false              // --no-parent

	if assignee, _ := cmd.Flags().GetString("assignee"); assignee != "" {
		if assignee == "me" {
			// We'll need to get the current user's ID
			// For now, we'll use a special marker
			filter["assignee"] = map[string]interface{}{"isMe": map[string]interface{}{"eq": true}}
		} else {
			filter["assignee"] = map[string]interface{}{"email": map[string]interface{}{"eq": assignee}}
		}
	}

	state, _ := cmd.Flags().GetString("state")
	if state != "" {
		filter["state"] = map[string]interface{}{"name": map[string]interface{}{"eq": state}}
	} else {
		// Only filter out completed issues if no specific state is requested
		includeCompleted, _ := cmd.Flags().GetBool("include-completed")
		if !includeCompleted {
			// Filter out completed and canceled states
			filter["state"] = map[string]interface{}{
				"type": map[string]interface{}{
					"nin": []string{"completed", "canceled"},
				},
			}
		}
	}

	if team, _ := cmd.Flags().GetString("team"); team != "" {
		filter["team"] = map[string]interface{}{"key": map[string]interface{}{"eq": team}}
	}

	if priority, _ := cmd.Flags().GetInt("priority"); priority != -1 {
		filter["priority"] = map[string]interface{}{"eq": priority}
	}

	// Handle newer-than filter
	newerThan, _ := cmd.Flags().GetString("newer-than")
	createdAt, err := utils.ParseTimeExpression(newerThan)
	if err != nil {
		plaintext := viper.GetBool("plaintext")
		jsonOut := viper.GetBool("json")
		output.Error(fmt.Sprintf("Invalid newer-than value: %v", err), plaintext, jsonOut)
		os.Exit(1)
	}
    if createdAt != "" {
        filter["createdAt"] = map[string]interface{}{"gte": createdAt}
    }

    // Optional: project filter (by ID)
    if cmd.Flags().Changed("project") {
        proj, _ := cmd.Flags().GetString("project")
        proj = strings.TrimSpace(proj)
        if proj != "" {
            if !isValidUUID(proj) {
                plaintext := viper.GetBool("plaintext")
                jsonOut := viper.GetBool("json")
                output.Error(fmt.Sprintf("Invalid project ID format: %s", proj), plaintext, jsonOut)
                os.Exit(1)
            }
            // Prefer nested project.id equality for filtering
            filter["project"] = map[string]interface{}{
                "id": map[string]interface{}{"eq": proj},
            }
        }
    }

    // Optional: label filters
    labelsFilter := map[string]interface{}{}

    // Primary AND filter (--label). If present, it takes precedence over --label-any/--label-not/--unlabeled.
    if cmd.Flags().Changed("label") {
        labelsCSV, _ := cmd.Flags().GetString("label")
        if strings.TrimSpace(labelsCSV) != "" {
            ids, err := lookupIssueLabelIDsByNames(context.Background(), client, labelsCSV)
            if err != nil {
                plaintext := viper.GetBool("plaintext")
                jsonOut := viper.GetBool("json")
                output.Error(err.Error(), plaintext, jsonOut)
                os.Exit(1)
            }
            requiredLabelIDs = ids
            labelsFilter["some"] = map[string]interface{}{
                "id": map[string]interface{}{"in": ids},
            }
            // If other label flags are also set, warn (non-JSON) they are ignored
            if (cmd.Flags().Changed("label-any") || cmd.Flags().Changed("label-not") || cmd.Flags().Changed("unlabeled")) && !viper.GetBool("json") {
                fmt.Println("Warning: --label specified; ignoring --label-any/--label-not/--unlabeled")
            }
        } else {
            // Empty string with --label for list/search doesn't make sense; ignore silently
        }
    } else {
        // OR semantics (--label-any)
        if cmd.Flags().Changed("label-any") {
            csv, _ := cmd.Flags().GetString("label-any")
            if strings.TrimSpace(csv) != "" {
                ids, err := lookupIssueLabelIDsByNames(context.Background(), client, csv)
                if err != nil {
                    plaintext := viper.GetBool("plaintext")
                    jsonOut := viper.GetBool("json")
                    output.Error(err.Error(), plaintext, jsonOut)
                    os.Exit(1)
                }
                anyLabelIDs = ids
                labelsFilter["some"] = map[string]interface{}{
                    "id": map[string]interface{}{"in": ids},
                }
            }
        }
        // NOT semantics (--label-not)
        if cmd.Flags().Changed("label-not") {
            csv, _ := cmd.Flags().GetString("label-not")
            if strings.TrimSpace(csv) != "" {
                ids, err := lookupIssueLabelIDsByNames(context.Background(), client, csv)
                if err != nil {
                    plaintext := viper.GetBool("plaintext")
                    jsonOut := viper.GetBool("json")
                    output.Error(err.Error(), plaintext, jsonOut)
                    os.Exit(1)
                }
                notLabelIDs = ids
                // Merge with existing labelsFilter if present
                labelsFilter["none"] = map[string]interface{}{
                    "id": map[string]interface{}{"in": ids},
                }
            }
        }
        // Unlabeled only (--unlabeled). Apply client-side only to avoid API quirks.
        if cmd.Flags().Changed("unlabeled") {
            unlabeledOnly, _ = cmd.Flags().GetBool("unlabeled")
            if unlabeledOnly {
                // If combined with 'any' or 'not', warn (non-JSON) and ignore others
                if (len(anyLabelIDs) > 0 || len(notLabelIDs) > 0) && !viper.GetBool("json") {
                    fmt.Println("Warning: --unlabeled specified; ignoring --label-any/--label-not")
                }
                // Clear server-side label filter to avoid conflicts
                labelsFilter = map[string]interface{}{}
                anyLabelIDs = nil
                notLabelIDs = nil
            }
        }
    }

    if len(labelsFilter) > 0 {
        filter["labels"] = labelsFilter
    }
    // Parent filters (mutually exclusive logic)
    if cmd.Flags().Changed("has-parent") && cmd.Flags().Changed("no-parent") {
        plaintext := viper.GetBool("plaintext")
        jsonOut := viper.GetBool("json")
        output.Error("Cannot combine --has-parent and --no-parent", plaintext, jsonOut)
        os.Exit(1)
    }
    if cmd.Flags().Changed("parent") && (cmd.Flags().Changed("has-parent") || cmd.Flags().Changed("no-parent")) {
        plaintext := viper.GetBool("plaintext")
        jsonOut := viper.GetBool("json")
        output.Error("Cannot combine --parent with --has-parent/--no-parent", plaintext, jsonOut)
        os.Exit(1)
    }
    if cmd.Flags().Changed("parent") {
        ident, _ := cmd.Flags().GetString("parent")
        ident = strings.TrimSpace(ident)
        if ident != "" {
            // Resolve identifier to node ID
            p, err := client.GetIssue(context.Background(), ident)
            if err != nil {
                plaintext := viper.GetBool("plaintext")
                jsonOut := viper.GetBool("json")
                output.Error(fmt.Sprintf("Parent issue '%s' not found", ident), plaintext, jsonOut)
                os.Exit(1)
            }
            parentNodeID = p.ID
            // Best-effort server filter on parent.id
            filter["parent"] = map[string]interface{}{
                "id": map[string]interface{}{"eq": parentNodeID},
            }
        }
    }
    if cmd.Flags().Changed("has-parent") {
        hasParent, _ = cmd.Flags().GetBool("has-parent")
    }
    if cmd.Flags().Changed("no-parent") {
        noParent, _ = cmd.Flags().GetBool("no-parent")
    }

    return filter, requiredLabelIDs, anyLabelIDs, notLabelIDs, unlabeledOnly, parentNodeID, hasParent, noParent
}

// filterIssuesByLabels enforces AND semantics for label IDs on a fetched collection.
func filterIssuesAdvanced(issues *api.Issues, requireAll, any, not []string, unlabeled bool) *api.Issues {
    if issues == nil {
        return issues
    }
    // Build lookup sets
    toSet := func(arr []string) map[string]struct{} {
        if len(arr) == 0 {
            return nil
        }
        m := make(map[string]struct{}, len(arr))
        for _, v := range arr {
            m[v] = struct{}{}
        }
        return m
    }
    req := toSet(requireAll)
    anySet := toSet(any)
    notSet := toSet(not)

    keep := func(issue api.Issue) bool {
        // Unlabeled only
        if unlabeled {
            return issue.Labels == nil || len(issue.Labels.Nodes) == 0
        }
        // Build label set
        have := make(map[string]struct{})
        if issue.Labels != nil {
            for _, l := range issue.Labels.Nodes {
                have[l.ID] = struct{}{}
            }
        }
        // Require ALL
        if req != nil {
            for id := range req {
                if _, ok := have[id]; !ok {
                    return false
                }
            }
        }
        // Require ANY
        if anySet != nil {
            anyOK := false
            for id := range anySet {
                if _, ok := have[id]; ok {
                    anyOK = true
                    break
                }
            }
            if !anyOK {
                return false
            }
        }
        // Exclude NOT
        if notSet != nil {
            for id := range notSet {
                if _, ok := have[id]; ok {
                    return false
                }
            }
        }
        return true
    }

    out := make([]api.Issue, 0, len(issues.Nodes))
    for _, is := range issues.Nodes {
        if keep(is) {
            out = append(out, is)
        }
    }
    filtered := *issues
    filtered.Nodes = out
    return &filtered
}

// filterIssuesByParent applies parent-based filters client-side.
func filterIssuesByParent(issues *api.Issues, parentID string, wantHas, wantNo bool) *api.Issues {
    if issues == nil {
        return issues
    }
    // No parent filters: return as-is
    if parentID == "" && !wantHas && !wantNo {
        return issues
    }
    keep := func(is api.Issue) bool {
        has := is.Parent != nil && is.Parent.ID != ""
        if parentID != "" {
            return has && is.Parent.ID == parentID
        }
        if wantHas {
            return has
        }
        if wantNo {
            return !has
        }
        return true
    }
    out := make([]api.Issue, 0, len(issues.Nodes))
    for _, is := range issues.Nodes {
        if keep(is) {
            out = append(out, is)
        }
    }
    filtered := *issues
    filtered.Nodes = out
    return &filtered
}

func priorityToString(priority int) string {
	switch priority {
	case 0:
		return "None"
	case 1:
		return "Urgent"
	case 2:
		return "High"
	case 3:
		return "Normal"
	case 4:
		return "Low"
	default:
		return "Unknown"
	}
}

func truncateString(s string, maxLen int) string {
	if len(s) <= maxLen {
		return s
	}
	return s[:maxLen-3] + "..."
}

var issueAssignCmd = &cobra.Command{
	Use:   "assign [issue-id]",
	Short: "Assign issue to yourself",
	Long:  `Assign an issue to yourself.`,
	Args:  cobra.ExactArgs(1),
	Run: func(cmd *cobra.Command, args []string) {
		plaintext := viper.GetBool("plaintext")
		jsonOut := viper.GetBool("json")

		authHeader, err := auth.GetAuthHeader()
		if err != nil {
			output.Error("Not authenticated. Run 'linctl auth' first.", plaintext, jsonOut)
			os.Exit(1)
		}

		client := api.NewClient(authHeader)

		// Get current user
		viewer, err := client.GetViewer(context.Background())
		if err != nil {
			output.Error(fmt.Sprintf("Failed to get current user: %v", err), plaintext, jsonOut)
			os.Exit(1)
		}

		// Update issue with assignee
		input := map[string]interface{}{
			"assigneeId": viewer.ID,
		}

		issue, err := client.UpdateIssue(context.Background(), args[0], input)
		if err != nil {
			output.Error(fmt.Sprintf("Failed to assign issue: %v", err), plaintext, jsonOut)
			os.Exit(1)
		}

		if jsonOut {
			output.JSON(issue)
		} else if plaintext {
			fmt.Printf("Assigned %s to %s\n", issue.Identifier, viewer.Name)
		} else {
			fmt.Printf("%s Assigned %s to %s\n",
				color.New(color.FgGreen).Sprint("✓"),
				color.New(color.FgCyan, color.Bold).Sprint(issue.Identifier),
				color.New(color.FgCyan).Sprint(viewer.Name))
		}
	},
}

var issueCreateCmd = &cobra.Command{
	Use:     "create",
	Aliases: []string{"new"},
	Short:   "Create a new issue",
	Long:    `Create a new issue in Linear.`,
	Run: func(cmd *cobra.Command, args []string) {
		plaintext := viper.GetBool("plaintext")
		jsonOut := viper.GetBool("json")

		authHeader, err := auth.GetAuthHeader()
		if err != nil {
			output.Error("Not authenticated. Run 'linctl auth' first.", plaintext, jsonOut)
			os.Exit(1)
		}

		client := api.NewClient(authHeader)

		// Get flags
		title, _ := cmd.Flags().GetString("title")
		description, _ := cmd.Flags().GetString("description")
		teamKey, _ := cmd.Flags().GetString("team")
		priority, _ := cmd.Flags().GetInt("priority")
		assignToMe, _ := cmd.Flags().GetBool("assign-me")

		if title == "" {
			output.Error("Title is required (--title)", plaintext, jsonOut)
			os.Exit(1)
		}

		if teamKey == "" {
			output.Error("Team is required (--team)", plaintext, jsonOut)
			os.Exit(1)
		}

		// Get team ID from key
		team, err := client.GetTeam(context.Background(), teamKey)
		if err != nil {
			output.Error(fmt.Sprintf("Failed to find team '%s': %v", teamKey, err), plaintext, jsonOut)
			os.Exit(1)
		}

		// Build input
		input := map[string]interface{}{
			"title":  title,
			"teamId": team.ID,
		}

		if description != "" {
			input["description"] = description
		}

		if priority >= 0 && priority <= 4 {
			input["priority"] = priority
		}

		if assignToMe {
			viewer, err := client.GetViewer(context.Background())
			if err != nil {
				output.Error(fmt.Sprintf("Failed to get current user: %v", err), plaintext, jsonOut)
				os.Exit(1)
			}
			input["assigneeId"] = viewer.ID
		}

        // Handle project assignment
        if cmd.Flags().Changed("project") {
			projectID, _ := cmd.Flags().GetString("project")
			if val, ok, err := buildProjectInput(projectID); err != nil {
				output.Error(err.Error(), plaintext, jsonOut)
				os.Exit(1)
			} else if ok {
				// For create, "unassigned" is equivalent to not setting project
				if val != nil {
					input["projectId"] = val
				}
			}
        }

        // Handle parent assignment (sub-issue)
        if cmd.Flags().Changed("parent") {
            parentIdent, _ := cmd.Flags().GetString("parent")
            parentIdent = strings.TrimSpace(parentIdent)
            if parentIdent != "" && parentIdent != "unassigned" {
                // Resolve to node ID
                p, err := client.GetIssue(context.Background(), parentIdent)
                if err != nil {
                    output.Error(fmt.Sprintf("Parent issue '%s' not found", parentIdent), plaintext, jsonOut)
                    os.Exit(1)
                }
                input["parentId"] = p.ID
            }
        }

        // Handle label assignment on create (optional)
        if cmd.Flags().Changed("label") {
			labelsCSV, _ := cmd.Flags().GetString("label")
			// Empty string means clear (no labels) — equivalent to not setting
			if strings.TrimSpace(labelsCSV) != "" {
				ids, err := lookupIssueLabelIDsByNames(context.Background(), client, labelsCSV)
				if err != nil {
					output.Error(err.Error(), plaintext, jsonOut)
					os.Exit(1)
				}
				input["labelIds"] = ids
			} else {
				input["labelIds"] = []string{}
			}
		}

		// Create issue
		issue, err := client.CreateIssue(context.Background(), input)
		if err != nil {
			// Standardize project not-found error when a project was provided
			if cmd.Flags().Changed("project") {
				projectID, _ := cmd.Flags().GetString("project")
				if projectID != "" && projectID != "unassigned" && isProjectNotFoundErr(err) {
					output.Error(fmt.Sprintf("Project '%s' not found", projectID), plaintext, jsonOut)
					os.Exit(1)
				}
			}
			output.Error(fmt.Sprintf("Failed to create issue: %v", err), plaintext, jsonOut)
			os.Exit(1)
		}

		if jsonOut {
			output.JSON(issue)
		} else if plaintext {
			fmt.Printf("Created issue %s: %s\n", issue.Identifier, issue.Title)
			if issue.Project != nil {
				fmt.Printf("Project: %s\n", issue.Project.Name)
			}
		} else {
			fmt.Printf("%s Created issue %s: %s\n",
				color.New(color.FgGreen).Sprint("✓"),
				color.New(color.FgCyan, color.Bold).Sprint(issue.Identifier),
				issue.Title)
			if issue.Assignee != nil {
				fmt.Printf("  Assigned to: %s\n", color.New(color.FgCyan).Sprint(issue.Assignee.Name))
			}
			if issue.Project != nil {
				fmt.Printf("  Project: %s\n", color.New(color.FgBlue).Sprint(issue.Project.Name))
			}
		}
	},
}

var issueUpdateCmd = &cobra.Command{
	Use:   "update [issue-id]",
	Short: "Update an issue",
	Long: `Update various fields of an issue.

Examples:
  linctl issue update LIN-123 --title "New title"
  linctl issue update LIN-123 --description "Updated description"
  linctl issue update LIN-123 --assignee john.doe@company.com
  linctl issue update LIN-123 --state "In Progress"
  linctl issue update LIN-123 --priority 1
  linctl issue update LIN-123 --due-date "2024-12-31"
  linctl issue update LIN-123 --title "New title" --assignee me --priority 2`,
	Args: cobra.ExactArgs(1),
	Run: func(cmd *cobra.Command, args []string) {
		plaintext := viper.GetBool("plaintext")
		jsonOut := viper.GetBool("json")

		authHeader, err := auth.GetAuthHeader()
		if err != nil {
			output.Error("Not authenticated. Run 'linctl auth' first.", plaintext, jsonOut)
			os.Exit(1)
		}

		client := api.NewClient(authHeader)

        // Build update input
        input := make(map[string]interface{})

        // Handle title update
        if cmd.Flags().Changed("title") {
			title, _ := cmd.Flags().GetString("title")
			input["title"] = title
		}

		// Handle description update
		if cmd.Flags().Changed("description") {
			description, _ := cmd.Flags().GetString("description")
			input["description"] = description
		}

		// Handle assignee update
		if cmd.Flags().Changed("assignee") {
			assignee, _ := cmd.Flags().GetString("assignee")
			switch assignee {
			case "me":
				// Get current user
				viewer, err := client.GetViewer(context.Background())
				if err != nil {
					output.Error(fmt.Sprintf("Failed to get current user: %v", err), plaintext, jsonOut)
					os.Exit(1)
				}
				input["assigneeId"] = viewer.ID
			case "unassigned", "":
				input["assigneeId"] = nil
			default:
				// Look up user by email
				users, err := client.GetUsers(context.Background(), 100, "", "")
				if err != nil {
					output.Error(fmt.Sprintf("Failed to get users: %v", err), plaintext, jsonOut)
					os.Exit(1)
				}

				var foundUser *api.User
				for _, user := range users.Nodes {
					if user.Email == assignee || user.Name == assignee {
						foundUser = &user
						break
					}
				}

				if foundUser == nil {
					output.Error(fmt.Sprintf("User not found: %s", assignee), plaintext, jsonOut)
					os.Exit(1)
				}

				input["assigneeId"] = foundUser.ID
			}
		}

		// Handle state update
		if cmd.Flags().Changed("state") {
			stateName, _ := cmd.Flags().GetString("state")

			// First, get the issue to know which team it belongs to
			issue, err := client.GetIssue(context.Background(), args[0])
			if err != nil {
				output.Error(fmt.Sprintf("Failed to get issue: %v", err), plaintext, jsonOut)
				os.Exit(1)
			}

			// Get available states for the team
			states, err := client.GetTeamStates(context.Background(), issue.Team.Key)
			if err != nil {
				output.Error(fmt.Sprintf("Failed to get team states: %v", err), plaintext, jsonOut)
				os.Exit(1)
			}

			// Find the state by name (case-insensitive)
			var stateID string
			for _, state := range states {
				if strings.EqualFold(state.Name, stateName) {
					stateID = state.ID
					break
				}
			}

			if stateID == "" {
				// Show available states
				var stateNames []string
				for _, state := range states {
					stateNames = append(stateNames, state.Name)
				}
				output.Error(fmt.Sprintf("State '%s' not found. Available states: %s", stateName, strings.Join(stateNames, ", ")), plaintext, jsonOut)
				os.Exit(1)
			}

			input["stateId"] = stateID
		}

		// Handle priority update
		if cmd.Flags().Changed("priority") {
			priority, _ := cmd.Flags().GetInt("priority")
			input["priority"] = priority
		}

		// Handle due date update
		if cmd.Flags().Changed("due-date") {
			dueDate, _ := cmd.Flags().GetString("due-date")
			if dueDate == "" {
				input["dueDate"] = nil
			} else {
				input["dueDate"] = dueDate
			}
		}

			// Handle project assignment update
			if cmd.Flags().Changed("project") {
				projectID, _ := cmd.Flags().GetString("project")
				if val, ok, err := buildProjectInput(projectID); err != nil {
					output.Error(err.Error(), plaintext, jsonOut)
					os.Exit(1)
				} else if ok {
					input["projectId"] = val
				}
			}

			// Handle parent update (set/remove)
			if cmd.Flags().Changed("parent") {
				parentIdent, _ := cmd.Flags().GetString("parent")
				parentIdent = strings.TrimSpace(parentIdent)
				if parentIdent == "unassigned" || parentIdent == "" {
					// Explicitly remove parent
					input["parentId"] = nil
				} else {
					p, err := client.GetIssue(context.Background(), parentIdent)
					if err != nil {
						output.Error(fmt.Sprintf("Parent issue '%s' not found", parentIdent), plaintext, jsonOut)
						os.Exit(1)
					}
					input["parentId"] = p.ID
				}
			}

		// Handle label operations
		// Precedence: --label (set/clear) takes precedence over add/remove
		labelSet := cmd.Flags().Changed("label")
		addSet := cmd.Flags().Changed("add-label")
		removeSet := cmd.Flags().Changed("remove-label")
		if labelSet {
			labelsCSV, _ := cmd.Flags().GetString("label")
			if strings.TrimSpace(labelsCSV) == "" {
				// Explicit clear all labels
				input["labelIds"] = []string{}
			} else {
				ids, err := lookupIssueLabelIDsByNames(context.Background(), client, labelsCSV)
				if err != nil {
					output.Error(err.Error(), plaintext, jsonOut)
					os.Exit(1)
				}
				input["labelIds"] = ids
			}
			// If add/remove also provided, warn that they are ignored
			if (addSet || removeSet) && !jsonOut {
				fmt.Println("Warning: --label specified; ignoring --add-label/--remove-label as per precedence rule")
			}
		} else {
			if addSet {
				addCSV, _ := cmd.Flags().GetString("add-label")
				if strings.TrimSpace(addCSV) != "" {
					ids, err := lookupIssueLabelIDsByNames(context.Background(), client, addCSV)
					if err != nil {
						output.Error(err.Error(), plaintext, jsonOut)
						os.Exit(1)
					}
                    input["addedLabelIds"] = ids
				}
			}
			if removeSet {
				removeCSV, _ := cmd.Flags().GetString("remove-label")
				if strings.TrimSpace(removeCSV) != "" {
					ids, err := lookupIssueLabelIDsByNames(context.Background(), client, removeCSV)
					if err != nil {
						output.Error(err.Error(), plaintext, jsonOut)
						os.Exit(1)
					}
                    input["removedLabelIds"] = ids
				}
			}
		}

		// Check if any updates were specified
		if len(input) == 0 {
			output.Error("No updates specified. Use flags to specify what to update.", plaintext, jsonOut)
			os.Exit(1)
		}

		// Update the issue
		issue, err := client.UpdateIssue(context.Background(), args[0], input)
		if err != nil {
			// Standardize project not-found error when a project was provided
			if cmd.Flags().Changed("project") {
				projectID, _ := cmd.Flags().GetString("project")
				if projectID != "" && projectID != "unassigned" && isProjectNotFoundErr(err) {
					output.Error(fmt.Sprintf("Project '%s' not found", projectID), plaintext, jsonOut)
					os.Exit(1)
				}
			}
			output.Error(fmt.Sprintf("Failed to update issue: %v", err), plaintext, jsonOut)
			os.Exit(1)
		}

		if jsonOut {
			output.JSON(issue)
		} else if plaintext {
			fmt.Printf("Updated issue %s\n", issue.Identifier)
		} else {
			output.Success(fmt.Sprintf("Updated issue %s", issue.Identifier), plaintext, jsonOut)
		}
	},
}

func init() {
	rootCmd.AddCommand(issueCmd)
	issueCmd.AddCommand(issueListCmd)
	issueCmd.AddCommand(issueSearchCmd)
	issueCmd.AddCommand(issueGetCmd)
	issueCmd.AddCommand(issueAssignCmd)
	issueCmd.AddCommand(issueCreateCmd)
	issueCmd.AddCommand(issueUpdateCmd)

	// Issue list flags
	issueListCmd.Flags().StringP("assignee", "a", "", "Filter by assignee (email or 'me')")
	issueListCmd.Flags().StringP("state", "s", "", "Filter by state name")
	issueListCmd.Flags().StringP("team", "t", "", "Filter by team key")
	issueListCmd.Flags().IntP("priority", "r", -1, "Filter by priority (0=None, 1=Urgent, 2=High, 3=Normal, 4=Low)")
	issueListCmd.Flags().IntP("limit", "l", 50, "Maximum number of issues to fetch")
	issueListCmd.Flags().BoolP("include-completed", "c", false, "Include completed and canceled issues")
	issueListCmd.Flags().StringP("sort", "o", "linear", "Sort order: linear (default), created, updated")
	issueListCmd.Flags().StringP("newer-than", "n", "", "Show issues created after this time (default: 6_months_ago, use 'all_time' for no filter)")
    issueListCmd.Flags().String("project", "", "Filter by project ID (UUID)")
    issueListCmd.Flags().String("label", "", "Filter by labels (comma-separated names). AND semantics for multiple labels.")
    issueListCmd.Flags().String("label-any", "", "Match any of these labels (comma-separated names). OR semantics.")
    issueListCmd.Flags().String("label-not", "", "Exclude issues that have any of these labels (comma-separated names).")
    issueListCmd.Flags().Bool("unlabeled", false, "Only issues with no labels (cannot be combined with label filters)")
    issueListCmd.Flags().String("parent", "", "Filter by parent issue identifier (e.g., 'RAE-123')")
    issueListCmd.Flags().Bool("has-parent", false, "Only sub-issues (issues that have a parent)")
    issueListCmd.Flags().Bool("no-parent", false, "Only top-level issues (no parent)")

	// Issue search flags
	issueSearchCmd.Flags().StringP("assignee", "a", "", "Filter by assignee (email or 'me')")
	issueSearchCmd.Flags().StringP("state", "s", "", "Filter by state name")
	issueSearchCmd.Flags().StringP("team", "t", "", "Filter by team key")
	issueSearchCmd.Flags().IntP("priority", "r", -1, "Filter by priority (0=None, 1=Urgent, 2=High, 3=Normal, 4=Low)")
	issueSearchCmd.Flags().IntP("limit", "l", 50, "Maximum number of issues to fetch")
	issueSearchCmd.Flags().BoolP("include-completed", "c", false, "Include completed and canceled issues")
	issueSearchCmd.Flags().Bool("include-archived", false, "Include archived issues in results")
	issueSearchCmd.Flags().StringP("sort", "o", "linear", "Sort order: linear (default), created, updated")
	issueSearchCmd.Flags().StringP("newer-than", "n", "", "Show issues created after this time (default: 6_months_ago, use 'all_time' for no filter)")
    issueSearchCmd.Flags().String("project", "", "Filter by project ID (UUID)")
    issueSearchCmd.Flags().String("label", "", "Filter by labels (comma-separated names). AND semantics for multiple labels.")
    issueSearchCmd.Flags().String("label-any", "", "Match any of these labels (comma-separated names). OR semantics.")
    issueSearchCmd.Flags().String("label-not", "", "Exclude issues that have any of these labels (comma-separated names).")
    issueSearchCmd.Flags().Bool("unlabeled", false, "Only issues with no labels (cannot be combined with label filters)")
    issueSearchCmd.Flags().String("parent", "", "Filter by parent issue identifier (e.g., 'RAE-123')")
    issueSearchCmd.Flags().Bool("has-parent", false, "Only sub-issues (issues that have a parent)")
    issueSearchCmd.Flags().Bool("no-parent", false, "Only top-level issues (no parent)")

	// Issue create flags
	issueCreateCmd.Flags().StringP("title", "", "", "Issue title (required)")
	issueCreateCmd.Flags().StringP("description", "d", "", "Issue description")
	issueCreateCmd.Flags().StringP("team", "t", "", "Team key (required)")
	issueCreateCmd.Flags().Int("priority", 3, "Priority (0=None, 1=Urgent, 2=High, 3=Normal, 4=Low)")
	issueCreateCmd.Flags().BoolP("assign-me", "m", false, "Assign to yourself")
	issueCreateCmd.Flags().String("project", "", "Project ID to assign issue to")
	issueCreateCmd.Flags().String("label", "", "Comma-separated labels to set during creation (e.g., 'bug,backend')")
	issueCreateCmd.Flags().String("parent", "", "Parent issue identifier (e.g., 'RAE-123') to create a sub-issue")
	_ = issueCreateCmd.MarkFlagRequired("title")
	_ = issueCreateCmd.MarkFlagRequired("team")

	// Issue update flags
	issueUpdateCmd.Flags().String("title", "", "New title for the issue")
	issueUpdateCmd.Flags().StringP("description", "d", "", "New description for the issue")
	issueUpdateCmd.Flags().StringP("assignee", "a", "", "Assignee (email, name, 'me', or 'unassigned')")
	issueUpdateCmd.Flags().StringP("state", "s", "", "State name (e.g., 'Todo', 'In Progress', 'Done')")
	issueUpdateCmd.Flags().Int("priority", -1, "Priority (0=None, 1=Urgent, 2=High, 3=Normal, 4=Low)")
	issueUpdateCmd.Flags().String("due-date", "", "Due date (YYYY-MM-DD format, or empty to remove)")
	issueUpdateCmd.Flags().String("project", "", "Project ID to assign issue to (or 'unassigned' to remove)")
	issueUpdateCmd.Flags().String("label", "", "Set labels exactly (comma-separated). Empty string clears all labels. Takes precedence over add/remove.")
	issueUpdateCmd.Flags().String("add-label", "", "Add labels (comma-separated). Ignored if --label is provided.")
	issueUpdateCmd.Flags().String("remove-label", "", "Remove labels (comma-separated). Ignored if --label is provided.")
	issueUpdateCmd.Flags().String("parent", "", "Parent issue identifier to set (or 'unassigned' to remove parent)")
}
