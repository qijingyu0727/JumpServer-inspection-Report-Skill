package main

import (
	"flag"
	"fmt"
	_ "github.com/go-sql-driver/mysql"
	_ "github.com/lib/pq"
	"inspect/pkg/common"
	"inspect/pkg/report"
	"inspect/pkg/task"
	"os"
)

const DefaultJMSConfigPath = "/opt/jumpserver/config/config.txt"
const version = "dev"

var logger *common.Logger

func main() {
	logger = common.GetLogger()
	opts := task.Options{Logger: logger}
	defer opts.Clear()

	flag.Usage = func() {
		_, _ = fmt.Fprintf(os.Stderr, "JumpServer 巡检脚本工具, 版本: %s\n", version)
		_, _ = fmt.Fprintf(os.Stderr, "该工具用于自动化检查系统中各个组件的状态，包括网络连接、服务运行情况等。通过此工具，您可以快速识别潜在问题，提高系统维护效率。\n")
		_, _ = fmt.Fprintf(os.Stderr, "[使用方法]\n jms_inspect[exe] -参数选项 参数值\n")
		flag.PrintDefaults()
	}
	flag.StringVar(
		&opts.JMSConfigPath, "jc", DefaultJMSConfigPath, "堡垒机配置文件路径",
	)
	flag.StringVar(
		&opts.MachineInfoPath, "mt", opts.MachineInfoPath,
		"待巡检机器配置文件路径(查看脚本压缩包内 machine-demo.csv/yml 文件)",
	)
	flag.StringVar(
		&opts.ExcludeTask, "et", opts.ExcludeTask,
		"不执行的任务，多个任务中间用逗号隔开(rds、redis)",
	)
	flag.BoolVar(
		&opts.Debug, "debug", opts.Debug, "开启调试模式",
	)
	flag.BoolVar(
		&opts.Silent, "silent", opts.Silent, "是否静默执行，开启后将不输入非 Error 类型日志信息",
	)
	flag.BoolVar(
		&opts.AutoApprove, "auto-approve", opts.AutoApprove, "跳过机器检查后的继续执行确认",
	)
	flag.BoolVar(
		&opts.CheckOnly, "check-only", opts.CheckOnly, "仅执行配置与连通性检查，不生成报告",
	)
	flag.StringVar(
		&opts.OutputDir, "output-dir", opts.OutputDir, "报告输出目录；留空时使用默认 output/<timestamp>/",
	)
	flag.Parse()

	if opts.Silent {
		opts.Logger.SetSilent()
	}
	if opts.OutputDir != "" {
		if err := os.MkdirAll(opts.OutputDir, 0o700); err != nil {
			logger.Error("创建输出目录失败: %v\n", err)
			os.Exit(1)
		}
		common.OutputDir = opts.OutputDir
	}

	logger.Debug("开始检查配置等相关信息...")
	if err := opts.Valid(); err != nil {
		logger.Error("参数校验错误: %v\n", err)
		os.Exit(1)
	}
	if opts.CheckOnly {
		logger.Finished("检查通过")
		return
	}

	var resultSummary task.ResultSummary
	var result map[string]interface{}
	var abnormalResult []task.AbnormalMsg
	logger.MsgOneLine(common.NoType, "")
	logger.Info("巡检任务开始")
	// 设置全局信息
	resultSummary.SetGlobalInfo(&opts)
	// 执行摘要任务
	summaryTask := task.SummaryTask{}
	result, _ = task.DoTask(&summaryTask, &opts)
	resultSummary.VirtualResult = result
	// 执行组件依赖任务
	dbTask := task.DBTask{}
	result, _ = task.DoTask(&dbTask, &opts)
	resultSummary.DBResult = result

	var resultList []map[string]interface{}
	for _, m := range opts.MachineSet {
		executor := m.GetExecutor()
		executor.Logger = logger
		result, abnormalResult = executor.Execute(&opts)
		result["MachineType"] = m.Type
		result["MachineName"] = m.Name
		resultList = append(resultList, result)
		for _, r := range abnormalResult {
			r.NodeName = m.Name
			resultSummary.AbnormalResults = append(resultSummary.AbnormalResults, r)
		}
	}
	resultSummary.NormalResults = resultList

	hr := report.HtmlReport{Summary: &resultSummary}
	if err := hr.Generate(); err != nil {
		logger.Error("生成 HTML 格式报告错误: %s", err)
	}
	jr := report.JsonReport{Summary: &resultSummary}
	if err := jr.Generate(); err != nil {
		logger.Error("生成 Json 格式报告错误: %s", err)
	}
	er := report.ExcelReport{Summary: &resultSummary}
	if err := er.Generate(); err != nil {
		logger.Error("生成 Excel 格式报告错误: %s", err)
	}
	logger.Finished("巡检完成，请将此路径下的巡检文件发送给技术工程师: \n%s", hr.ReportDir)
}
