import pdb
import sys
import time
import random
import threading
import tensorflow as tf

from misc.utils import *
from .client import Client
from modules.federated import ServerModule

class Server(ServerModule):
    """ FedWeIT Server
    Performing fedweit server algorithms 
    Created by:
        Wonyong Jeong (wyjeong@kaist.ac.kr)
    """
    def __init__(self, args):
        super(Server, self).__init__(args, Client)
        # federated관련 server module initialization
        self.client_adapts = []

    def train_clients(self):
        cids = np.arange(self.args.num_clients).tolist()
        num_selection = int(round(self.args.num_clients*self.args.frac_clients))
        for curr_round in range(self.args.num_rounds*self.args.num_tasks):
        # round 수행, round수는 task수 x round 수
            self.updates = []
            self.curr_round = curr_round+1
            self.is_last_round = self.curr_round%self.args.num_rounds==0
            if self.is_last_round:
                self.client_adapts = []
            selected_ids = random.sample(cids, num_selection) # pick clients
            self.logger.print('server', 'round:{} train clients (selected_ids: {})'.format(curr_round, selected_ids))
            # train selected clients in parallel
            for clients in self.parallel_clients:
                self.threads = []
                for gid, cid in enumerate(clients):
                    client = self.clients[gid]
                    # selected_id는 federate의 fraction_fit에 대한 구현
                    selected = True if cid in selected_ids else False
                    with tf.device('/device:GPU:{}'.format(gid)):
                        # get_adapts에는 각 클라이언트로부터 수집된 레이어들의 adpative paramter 존재
                        thrd = threading.Thread(target=self.invoke_client, args=(client, cid, curr_round, selected, self.get_weights(), self.get_adapts()))
                        # invoke_client 함수를 통해 clinet 동작
                        self.threads.append(thrd)
                        thrd.start()
                # wait all threads each round
                for thrd in self.threads:
                    thrd.join()
                    # 해당 thread들이 멈출때까지 기다림
            # update
            aggr = self.train.aggregate(self.updates)
            self.set_weights(aggr)
        self.logger.print('server', 'done. ({}s)'.format(time.time()-self.start_time))
        sys.exit()

    def invoke_client(self, client, cid, curr_round, selected, weights, adapts):
        # 학습 수행, adapts는 task초반을 제외하고는 빈값
        update = client.train_one_round(cid, curr_round, selected, weights, adapts)
        # weights = global weights, adpats = knowledge base 의미
        if not update == None:
            self.updates.append(update)
            if self.is_last_round:
                self.client_adapts.append(client.get_adaptives())
                # 마지막 round에 각 클라이언트로부터 knowledge base 더하기
    
    # invoke client 수행시 초기 adaptive parameter 얻는 함수
    def get_adapts(self):
        if self.args.train_mode=='mask':
            return None
        elif self.curr_round%self.args.num_rounds==1 and not self.curr_round==1:
            # num_rounds는 task당 round, 즉 task의 첫번째 round에 수행
            # 첫번째 task에서는 none
            from_kb = []
            for lid, shape in enumerate(self.nets.shapes):
                shape = np.concatenate([self.nets.shapes[lid],[int(round(self.args.num_clients*self.args.frac_clients))]], axis=0)
                from_kb_l = np.zeros(shape)
                # 전체 모델 크기의 kb생성
                for cid, ca in enumerate(self.client_adapts):
                    try:
                        # 깊이 4의 layer를 상정하여 마지막 요소 client_id
                        # kb를 각 클라이언트로부터의 parameter로 채움
                        if len(shape)==5:
                            from_kb_l[:,:,:,:,cid] = ca[lid]
                        else:
                            from_kb_l[:,:,cid] = ca[lid]
                    except:
                        pdb.set_trace()
                from_kb.append(from_kb_l)
            return from_kb
        else:
            return None
        