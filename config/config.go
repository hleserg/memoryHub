// config/config.go
// Config loader for memoryHub.
// Loads memoryhub.config.yaml, merges with defaults.yaml, resolves ENV vars.
// See ARCHITECTURE.md §10 "Единый конфиг" — all config lives here.

package config

import (
	"fmt"
	"os"
	"strings"

	"github.com/spf13/viper"
)

// Config is the top-level configuration structure.
// All fields map 1:1 to memoryhub.config.yaml sections.
type Config struct {
	System               SystemConfig               `mapstructure:"system"`
	APIHub               APIHubConfig               `mapstructure:"api_hub"`
	KnowledgeGraph       KnowledgeGraphConfig       `mapstructure:"knowledge_graph"`
	Trust                TrustConfig                `mapstructure:"trust"`
	CorruptionProtection CorruptionProtectionConfig `mapstructure:"corruption_protection"`
	MCPServer            MCPServerConfig            `mapstructure:"mcp_server"`
	AgentMetrics         AgentMetricsConfig         `mapstructure:"agent_metrics"`
	HealthMonitoring     HealthMonitoringConfig     `mapstructure:"health_monitoring"`
	DisasterRecovery     DisasterRecoveryConfig     `mapstructure:"disaster_recovery"`
	GithubSnapshots      GithubSnapshotsConfig      `mapstructure:"github_snapshots"`
	Skills               SkillsConfig               `mapstructure:"skills"`
	Storage              StorageConfig              `mapstructure:"storage"`
	Integrations         IntegrationsConfig         `mapstructure:"integrations"`
}

type SystemConfig struct {
	Name        string `mapstructure:"name"`
	Version     string `mapstructure:"version"`
	Environment string `mapstructure:"environment"`
	LogLevel    string `mapstructure:"log_level"`
	LogFormat   string `mapstructure:"log_format"`
	DataDir     string `mapstructure:"data_dir"`
	ConfigDir   string `mapstructure:"config_dir"`
}

type APIHubConfig struct {
	Port          int             `mapstructure:"port"`
	Host          string          `mapstructure:"host"`
	TLS           TLSConfig       `mapstructure:"tls"`
	Keys          KeysConfig      `mapstructure:"keys"`
	RateLimit     RateLimitConfig `mapstructure:"rate_limit"`
	CORS          CORSConfig      `mapstructure:"cors"`
	MaxBodySizeKB int             `mapstructure:"max_body_size_kb"`
}

type TLSConfig struct {
	Enabled  bool   `mapstructure:"enabled"`
	CertPath string `mapstructure:"cert_path"`
	KeyPath  string `mapstructure:"key_path"`
}

type KeysConfig struct {
	RotationDays int    `mapstructure:"rotation_days"`
	MinLength    int    `mapstructure:"min_length"`
	Prefix       string `mapstructure:"prefix"`
}

type RateLimitConfig struct {
	WindowMS int                    `mapstructure:"window_ms"`
	Strategy string                 `mapstructure:"strategy"`
	Tiers    map[string]RateTier    `mapstructure:"tiers"`
	Headers  RateLimitHeadersConfig `mapstructure:"headers"`
}

type RateTier struct {
	WriteRPM    int `mapstructure:"write_rpm"`
	ReadRPM     int `mapstructure:"read_rpm"`
	BulkOpsHour int `mapstructure:"bulk_ops_hour"` // -1 = unlimited
}

type RateLimitHeadersConfig struct {
	Expose bool `mapstructure:"expose"`
}

type CORSConfig struct {
	Origins     []string `mapstructure:"origins"`
	Credentials bool     `mapstructure:"credentials"`
}

type KnowledgeGraphConfig struct {
	Engine           string          `mapstructure:"engine"`
	DBPath           string          `mapstructure:"db_path"`
	BufferPoolSizeMB int             `mapstructure:"buffer_pool_size_mb"`
	MaxThreads       int             `mapstructure:"max_threads"`
	Conflicts        ConflictsConfig `mapstructure:"conflicts"`
	Temporal         TemporalConfig  `mapstructure:"temporal"`
}

type ConflictsConfig struct {
	AutoDetect             bool `mapstructure:"auto_detect"`
	CheckIntervalSeconds   int  `mapstructure:"check_interval_seconds"`
	ResolutionTimeoutHours int  `mapstructure:"resolution_timeout_hours"`
}

type TemporalConfig struct {
	Enabled               bool `mapstructure:"enabled"`
	SnapshotRetentionDays int  `mapstructure:"snapshot_retention_days"`
}

type TrustConfig struct {
	AutoApproveThreshold float64                   `mapstructure:"auto_approve_threshold"`
	HumanReviewThreshold float64                   `mapstructure:"human_review_threshold"`
	VerificationWeights  VerificationWeightsConfig `mapstructure:"verification_weights"`
	Queue                TrustQueueConfig          `mapstructure:"queue"`
	HumanReview          HumanReviewConfig         `mapstructure:"human_review"`
	Quarantine           QuarantineConfig          `mapstructure:"quarantine"`
}

type VerificationWeightsConfig struct {
	FactChecker       float64 `mapstructure:"fact_checker"`
	AnomalyDetector   float64 `mapstructure:"anomaly_detector"`
	SourceCredibility float64 `mapstructure:"source_credibility"`
	ConflictScanner   float64 `mapstructure:"conflict_scanner"`
}

type TrustQueueConfig struct {
	MaxSize             int `mapstructure:"max_size"`
	ProcessingWorkers   int `mapstructure:"processing_workers"`
	ProcessingTimeoutMS int `mapstructure:"processing_timeout_ms"`
}

type HumanReviewConfig struct {
	EscalationHours int  `mapstructure:"escalation_hours"`
	NotifyOnNew     bool `mapstructure:"notify_on_new"`
}

type QuarantineConfig struct {
	AutoExpireDays int `mapstructure:"auto_expire_days"`
	MaxSize        int `mapstructure:"max_size"`
}

type CorruptionProtectionConfig struct {
	FactChecker     FactCheckerConfig     `mapstructure:"fact_checker"`
	AnomalyDetector AnomalyDetectorConfig `mapstructure:"anomaly_detector"`
	Checksums       ChecksumsConfig       `mapstructure:"checksums"`
}

type FactCheckerConfig struct {
	Enabled                       bool `mapstructure:"enabled"`
	FullScanIntervalHours         int  `mapstructure:"full_scan_interval_hours"`
	NewRecordsScanIntervalMinutes int  `mapstructure:"new_records_scan_interval_minutes"`
	BatchSize                     int  `mapstructure:"batch_size"`
}

type AnomalyDetectorConfig struct {
	Enabled                      bool    `mapstructure:"enabled"`
	BurstWriteThreshold          int     `mapstructure:"burst_write_threshold"`
	BurstWriteWindowMinutes      int     `mapstructure:"burst_write_window_minutes"`
	ConfidenceInflationThreshold float64 `mapstructure:"confidence_inflation_threshold"`
}

type ChecksumsConfig struct {
	Enabled      bool   `mapstructure:"enabled"`
	Algorithm    string `mapstructure:"algorithm"`
	VerifyOnRead bool   `mapstructure:"verify_on_read"`
	VerifyOnScan bool   `mapstructure:"verify_on_scan"`
}

type MCPServerConfig struct {
	Port                  int            `mapstructure:"port"`
	Host                  string         `mapstructure:"host"`
	Protocol              MCPProtocol    `mapstructure:"protocol"`
	MaxConnections        int            `mapstructure:"max_connections"`
	SessionTimeoutMinutes int            `mapstructure:"session_timeout_minutes"`
	MaxResponseSizeKB     int            `mapstructure:"max_response_size_kb"`
	Tools                 MCPToolsConfig `mapstructure:"tools"`
}

type MCPProtocol struct {
	Version string `mapstructure:"version"`
}

type MCPToolsConfig struct {
	MemorySearch MCPToolLimits    `mapstructure:"memory_search"`
	MemoryRecall MCPToolLimits    `mapstructure:"memory_recall"`
	GraphQuery   GraphQueryConfig `mapstructure:"graph_query"`
}

type MCPToolLimits struct {
	MaxLimit             int     `mapstructure:"max_limit"`
	DefaultLimit         int     `mapstructure:"default_limit"`
	DefaultMinConfidence float64 `mapstructure:"default_min_confidence"`
}

type GraphQueryConfig struct {
	MaxResults int  `mapstructure:"max_results"`
	TimeoutMS  int  `mapstructure:"timeout_ms"`
	ReadOnly   bool `mapstructure:"read_only"`
}

type AgentMetricsConfig struct {
	Ingest      MetricsIngestConfig   `mapstructure:"ingest"`
	Storage     MetricsStorageConfig  `mapstructure:"storage"`
	Feedback    MetricsFeedbackConfig `mapstructure:"feedback"`
	Credibility CredibilityConfig     `mapstructure:"credibility"`
}

type MetricsIngestConfig struct {
	Enabled              bool `mapstructure:"enabled"`
	BatchSize            int  `mapstructure:"batch_size"`
	FlushIntervalSeconds int  `mapstructure:"flush_interval_seconds"`
}

type MetricsStorageConfig struct {
	HotRetentionDays  int    `mapstructure:"hot_retention_days"`
	WarmRetentionDays int    `mapstructure:"warm_retention_days"`
	ColdArchive       string `mapstructure:"cold_archive"`
}

type MetricsFeedbackConfig struct {
	Enabled               bool `mapstructure:"enabled"`
	ComputeIntervalHours  int  `mapstructure:"compute_interval_hours"`
	MinRecordsForFeedback int  `mapstructure:"min_records_for_feedback"`
}

type CredibilityConfig struct {
	InitialScore    float64 `mapstructure:"initial_score"`
	DecayFactor     float64 `mapstructure:"decay_factor"`
	ApprovedBoost   float64 `mapstructure:"approved_boost"`
	RejectedPenalty float64 `mapstructure:"rejected_penalty"`
}

type HealthMonitoringConfig struct {
	Dashboard  DashboardConfig    `mapstructure:"dashboard"`
	Checks     HealthChecksConfig `mapstructure:"checks"`
	Thresholds ThresholdsConfig   `mapstructure:"thresholds"`
	Predictive PredictiveConfig   `mapstructure:"predictive"`
	Alerts     AlertsConfig       `mapstructure:"alerts"`
}

type DashboardConfig struct {
	Port                   int  `mapstructure:"port"`
	Enabled                bool `mapstructure:"enabled"`
	RefreshIntervalSeconds int  `mapstructure:"refresh_interval_seconds"`
}

type HealthChecksConfig struct {
	IntervalSeconds int `mapstructure:"interval_seconds"`
	TimeoutMS       int `mapstructure:"timeout_ms"`
}

type ThresholdsConfig struct {
	// TODO: Add per-component threshold structs
	// See ARCHITECTURE.md §4.8 for full threshold table
}

type PredictiveConfig struct {
	Enabled          bool `mapstructure:"enabled"`
	DiskForecastDays int  `mapstructure:"disk_forecast_days"`
}

type AlertsConfig struct {
	Routes        []AlertRoute       `mapstructure:"routes"`
	Deduplication AlertDeduplication `mapstructure:"deduplication"`
	QuietHours    AlertQuietHours    `mapstructure:"quiet_hours"`
}

type AlertRoute struct {
	Levels   []string `mapstructure:"levels"`
	Channels []string `mapstructure:"channels"`
	Prefix   string   `mapstructure:"prefix"`
}

type AlertDeduplication struct {
	WindowMinutes int `mapstructure:"window_minutes"`
}

type AlertQuietHours struct {
	Enabled          bool   `mapstructure:"enabled"`
	Start            string `mapstructure:"start"`
	End              string `mapstructure:"end"`
	Timezone         string `mapstructure:"timezone"`
	MinLevelOverride string `mapstructure:"min_level_override"`
}

type DisasterRecoveryConfig struct {
	// TODO: Add full DR config structs
	// See ARCHITECTURE.md §4.9
}

type GithubSnapshotsConfig struct {
	Enabled bool `mapstructure:"enabled"`
	// TODO: Add full GitHub Snapshots config structs
	// See ARCHITECTURE.md §4.10
}

type SkillsConfig struct {
	BaseDir      string          `mapstructure:"base_dir"`
	Endpoints    SkillsEndpoints `mapstructure:"endpoints"`
	DefaultAgent DefaultAgent    `mapstructure:"default_agent"`
}

type SkillsEndpoints struct {
	APIBase string `mapstructure:"api_base"`
	MCPBase string `mapstructure:"mcp_base"`
}

type DefaultAgent struct {
	ID string `mapstructure:"id"`
}

type StorageConfig struct {
	SQLite     SQLiteConfig     `mapstructure:"sqlite"`
	PostgreSQL PostgreSQLConfig `mapstructure:"postgresql"`
	Embeddings EmbeddingsConfig `mapstructure:"embeddings"`
}

type SQLiteConfig struct {
	Path        string `mapstructure:"path"`
	JournalMode string `mapstructure:"journal_mode"`
	CacheSizeMB int    `mapstructure:"cache_size_mb"`
}

type PostgreSQLConfig struct {
	Enabled  bool   `mapstructure:"enabled"`
	URL      string `mapstructure:"url"`
	PoolSize int    `mapstructure:"pool_size"`
}

type EmbeddingsConfig struct {
	Provider   string `mapstructure:"provider"`
	Model      string `mapstructure:"model"`
	Dimensions int    `mapstructure:"dimensions"`
}

type IntegrationsConfig struct {
	Telegram  TelegramConfig `mapstructure:"telegram"`
	LetheClaw LetheClaConfig `mapstructure:"letheclaw"`
}

type TelegramConfig struct {
	Enabled     bool   `mapstructure:"enabled"`
	AlertChatID string `mapstructure:"alert_chat_id"`
}

type LetheClaConfig struct {
	Enabled       bool   `mapstructure:"enabled"`
	URL           string `mapstructure:"url"`
	MigrationMode bool   `mapstructure:"migration_mode"`
}

// Load reads config from file and environment variables.
// Priority: ENV vars > config file > defaults.yaml
func Load(configPath string) (*Config, error) {
	v := viper.New()

	// Load defaults first
	v.SetConfigName("defaults")
	v.SetConfigType("yaml")
	v.AddConfigPath("./config")
	if err := v.ReadInConfig(); err != nil {
		// Defaults are optional
		fmt.Fprintf(os.Stderr, "warning: could not read defaults.yaml: %v\n", err)
	}

	// Load main config (overrides defaults)
	v.SetConfigFile(configPath)
	if err := v.MergeInConfig(); err != nil {
		return nil, fmt.Errorf("failed to read config file %s: %w", configPath, err)
	}

	// ENV var overrides — e.g., MEMORYHUB_SYSTEM_LOG_LEVEL
	v.SetEnvPrefix("MEMORYHUB")
	v.SetEnvKeyReplacer(strings.NewReplacer(".", "_"))
	v.AutomaticEnv()

	var cfg Config
	if err := v.Unmarshal(&cfg); err != nil {
		return nil, fmt.Errorf("failed to unmarshal config: %w", err)
	}

	if err := validate(&cfg); err != nil {
		return nil, fmt.Errorf("config validation failed: %w", err)
	}

	return &cfg, nil
}

// validate checks config for obvious errors.
// TODO: Add comprehensive validation (see ARCHITECTURE.md §10)
func validate(cfg *Config) error {
	// Verification weights must sum to ~1.0
	w := cfg.Trust.VerificationWeights
	sum := w.FactChecker + w.AnomalyDetector + w.SourceCredibility + w.ConflictScanner
	if sum < 0.99 || sum > 1.01 {
		return fmt.Errorf("trust.verification_weights must sum to 1.0, got %.2f", sum)
	}

	if cfg.Trust.AutoApproveThreshold < cfg.Trust.HumanReviewThreshold {
		return fmt.Errorf("trust.auto_approve_threshold must be >= human_review_threshold")
	}

	// TODO: Validate port numbers, paths, cron expressions, etc.

	return nil
}

// GetCORSOrigins returns allowed CORS origins from config.
// Satisfies the middleware.CORS interface requirement.
func (c *Config) GetCORSOrigins() []string {
	return c.APIHub.CORS.Origins
}
