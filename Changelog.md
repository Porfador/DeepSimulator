Current Situation - 10/06/26

Code works with event logs "LoanApp_simplified_test.csv", "Production.xes" and "RequestForPayment.xes"

"Loan_simplified_test.csv" and "Production.xes" can be runned directly with command.

Note: You need to adjust properties.yml file according to event log's colomn names. There are already adjustments for "Production.xes" and "LoanApp_simplified_test.csv". You only need to uncomment colomn names based on your file. 

```shell
python .\pipeline.py --file LoanApp_simplified_train.csv --no-evaluate --t_gen_epochs 20 --t_gen_max_eval 3 --s_gen_repetitions 3 --s_gen_max_eval 10 
```

Command parameters except "--no-evaluate" are optional and decrease computation time significantly, if you run the event log first time. In future runs there will be saved model for the event log and will be chosen as default.


To generate event logs from "RequestForPayment.xes", you need to run script "prepare_xes.py" with "RequestForPayment.xes". This will generate random end-timestamps for tasks. This is necessery because code requires two timestamps (Start-End) to run.

```shell
python .\scripts\prepare_xes.py --input input_files\event_logs\RequestForPayment.xes --output input_files\event_logs\RequestForPayment_prepared.xes
```

After that, you should run new file with script "mine_bpmn_from_xes.py". This is also necessery because code requires a pre-generated .bpmn file.
(Note: After small change in main code, it may be unnecessary. Because now code should generate this file itself, but not tested.)

```shell
python .\scripts\mine_bpmn_from_xes.py --file RequestForPayment_prepared.xes --mining-alg sm1 
```


Finally you can run the "RequestForPayment_prepared.xes" file with the main code.

```shell
python .\pipeline.py --file RequestForPayment_prepared.xes --update_gen --update_ia_gen --update_times_gen --exp_reps 1 --no-evaluate --s_gen_max_eval 10 --s_gen_repetitions 3 --t_gen_epochs 20 --t_gen_max_eval 3
```


Update: BPIChallange2019_3WayMatchingEC.csv also seems to be working now. Not sure about the workflow because I forgot the beginning, since it took so long. As I remember: I ran prepare_xes.py with the "BPIChallenge2019_3WayMatchingEC.csv" somehow. It wasn't working this morning. Then convert it to .csv back. Otherwise didn't work.

How to run:
```shell
python pipeline.py --file BPIChallenge2019_3WayMatchingEC_prepared_copy.csv --update_gen --update_ia_gen --update_times_gen --exp_reps 3 --no-evaluate --s_gen_max_eval 8 --s_gen_repetitions 3 --t_gen_epochs 20 --t_gen_max_eval 4
```

Some changes are made in ".\core_modules\instances_generator\prophet_generator.py", "./core_modules/times_allocator/intercase_features_calculator.py" and ".\extraction\log_replayer.py" file to run the "BPIChallenge2019_3WayMatchingEC.csv" event log, but later plans changed. If this changes affect other event logs, revert it.