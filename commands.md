Restart Service: sudo systemctl restart eocontroller
Check Service Status: sudo systemctl status eocontroller
Read Service Logs Live: sudo journalctl -u eocontroller -f
Copy Service File To Systemd Services: sudo cp eocontroller.service /etc/systemd/system/eocontroller.service
